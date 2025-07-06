---
title: Embedding machine code with the Zig Build System
layout: post
comments: true
hidden: true
---

For purposes that would become clear in a future post, I needed to solve a curious problem in the Zig build system. Prior to that, I knew very little about it. I expected the problem to be easy to solve, and it quite is, but I discovered a lot along the way.

The problem goes as follows. I want to assemble a listing with `nasm` and embed the machine code in the Zig program to be able to manipulate it as plain bytes. The curious part is that I want to utilize the build system to automate the process and cache/rebuild as needed.

I would try to present a more or less linear story with a few shoot-offs in an order that somewhat resembles the order I discovered the things. If you just want the answer, jump straight to the [conclusion](#conclusion).

<!--break-->

## Disclaimer

I'm still very new to Zig and its tooling so I might have gotten many things wrong.

Moreover, this is a very convoluted way to get assembly in your program. If you just want to implement some routines in assembly, assemble the listings into an object file and link against it (though you can set this up in the build system very similarly).

Please also note that a lot has changed in the build system in previous versions and a lot will change for sure. Zig is nowhere near to be stable. But I still believe that many fundamental things discussed in the post will hold up.

## Existing references

I won't give a ground-up introduction to the Zig build system. There are already awesome guides and resources to get started:
  - [zig build explained (in 3 parts)](https://zig.news/xq/zig-build-explained-part-1-59lf)
  - [Zig Build System Internals](https://mitchellh.com/zig/build-internals) by Mitchell Hashimoto
  - [Zig Build System Basics](https://www.youtube.com/watch?v=jy7w_7JZYyw) by [Loris Cro](https://github.com/kristoff-it)

I would like to build on top of them, and show some other details.

With the ceremony out of the way, there is the story.

## Here the story goes

Let's start with the initial setup. The Zig version is 0.14.1, and I am on a Linux machine.

Here is our main file:
{% include code-filename.html file="src/main.zig" %}
```zig
const std = @import("std");

pub fn main() !void {
    var stdout = std.io.getStdOut().writer();
    for (bytes) |b| {
        try stdout.print("{x:0>2}", .{b});
    }
    try stdout.writeAll("\n");
}

const bytes = @embedFile("example.bin");
```

It expects the file with the machine code to be available at module path `example.bin`. It embeds the file with the `@embedFile` built-in, which returns a pointer to a null-terminated byte array. The data is `comptime`-known and can be used in other `comptime` expressions. The `main` function prints the contents of the array to `stdout` in the hexadecimal format.

We will assemble the following listing:
{% include code-filename.html file="src/example.asm" %}
```nasm
bits 64
add rax, 5
```
It is intentionally very simple so we won't be overwhelmed by a large output.

The build system is set up as follows:
{% include code-filename.html file="build.zig" %}
```zig
const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    const exe_mod = b.createModule(.{
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });

    const exe = b.addExecutable(.{
        .name = "embed-example",
        .root_module = exe_mod,
    });

    b.installArtifact(exe);

    const run_cmd = b.addRunArtifact(exe);

    if (b.args) |args| {
        run_cmd.addArgs(args);
    }

    run_cmd.step.dependOn(b.getInstallStep());

    const run_step = b.step("run", "Run the program");
    run_step.dependOn(&run_cmd.step);
}
```

It is more or less what `zig init` would generate but without comments, unit-testing targets, and a separate library module. Here, we declare a module for `src/main.zig` and compile it as an executable named `embed-example`, we copy the executable to the installation location, and add a step to the `zig build` menu to run it.

At the moment, we have no instructions to assemble `src/example.asm` in the build script. So, let's proceed manually to check that we got the rest right:
```shell
$ nasm -fbin -o src/example.bin src/example.asm
```

Fortunately, everything builds, and we get an output:
```shell
$ zig build run
4883c005
```

We can verify that it works as expected by printing the contents or `src/example.bin`:
```shell
$ xxd -p src/example.bin
4883c005
```
...or by disassembling the output of the program:
```shell
$ zig build run | xxd -r -p | ndisasm -b 64 -
00000000  4883C005          add rax,byte +0x5
```

What's nice about this setup is that the output from the build system and the compiler goes to the `stderr` so it doesn't interfere with what gets piped in the pipeline.

## First attempt at automating the assembly process

Let's add a step to the build script to run `nasm` for us:
```zig
const nasm = b.addSystemCommand(&.{ "nasm", "-fbin", "-o", "src/example.bin", "src/example.asm" });
```

... and make the compilation step depend on it:
```zig
exe.step.dependOn(&nasm.step);
```

If we build and run the program again, it continues to work:
```shell
$ zig build run | xxd -r -p | ndisasm -b 64 -
00000000  4883C005          add rax,byte +0x5
```

And if we update the listing to:
```nasm
bits 64
add rax, 6
```
...and run:
```shell
$ zig build run | xxd -r -p | ndisasm -b 64 -
00000000  4883C006          add rax,byte +0x6
```
It reassembles the file and recompiles the `embed-example` binary without recompiling the build script. If we run it again, it won't recompile anything because the inputs to the compilation step haven't changed. Hooray!

However, this solution has three problems:
1. We have to make the `exe` step explicitly depend on the `nasm` step. Otherwise, the build system might run these steps in a wrong order or even in parallel because it doesn't know that `src/example.bin` is generated by another step.
2. The generated artifact ends up in the source tree. This might be a desirable behavior if we do code generation and want to commit and diff the generated code[^codegen-CI], but for such transient blobs this is not the case.
3. Even though, this command is run each time the build script executes[^nasm-no-cache-rerun], it doesn't get rerun in the `--watch` mode when `src/example.asm` changes because the build system doesn't know that the step depends on this file.

[^codegen-CI]: In this case, you'd want to add a switch for CI that checks that the files in the source tree are correct instead of overwriting them ([example](https://github.com/tigerbeetle/tigerbeetle/blob/6a6e39e68d2aea5683a3ddf2091042fd45e4ba16/build.zig#L1749)).
[^nasm-no-cache-rerun]: Despite of caching and provided that the `nasm` step is accessible from a top-level step like `install`.

## Getting rid of the explicit dependency

Let's create a module for `example.bin` and give it a special name:
```zig
exe_mod.addAnonymousImport("example", .{
    .root_source_file = b.path("src/example.bin"),
});
```

This snippet is equvalent to the following:
```zig
exe_mod.addImport("example", b.createModule(.{
    .root_source_file = b.path("src/example.bin"),
}));
```

We create an anonymous module with the root file `src/example.bin`[^non-zig-mod] and allow to import it by the name "example".

We can now reference and embed the file by the new alias:
```zig
const bytes = @embedFile("example");
```

[^non-zig-mod]: This seems somewhat hacky because modules are supposed for Zig code. However, there is a similar [example](https://gist.github.com/andrewrk/d1e6173448ab2bc350233cc20025ba56) by Andrew Kelley himself, so this seems to be valid in the current version as long as we use the module with `@embedFile` only and don't try to `@import` it.

That way, we have detached the import key from the actual file location and can play with the `.root_source_file` path.

In fact, the type of `b.path("src/example.bin")` is `LazyPath`. This is a tagged union whose true potential we are to discover later.

The `path` method on `Builder` allows us to reference a static file in the source tree:
```zig
/// References a file or directory relative to the source root.
pub fn path(b: *Build, sub_path: []const u8) LazyPath {
    if (fs.path.isAbsolute(sub_path)) {
        std.debug.panic("a long panic message", .{});
    }
    return .{ .src_path = .{
        .owner = b,
        .sub_path = sub_path,
    } };
}
```

However, `LazyPath` has another variant:
```zig
/// a reference to an existing or future path.
pub const lazypath = union(enum) {
    // ...

    generated: struct {
        file: *const generatedfile,

        /// the number of parent directories to go up.
        /// 0 means the generated file itself.
        /// 1 means the directory of the generated file.
        /// 2 means the parent of that directory, and so on.
        up: usize = 0,

        /// applied after `up`.
        sub_path: []const u8 = "",
    },

    // ...
};
```

it takes a pointer to a `generatedfile` which defined as follows:
```zig
/// a file that is generated by a build step.
/// this struct is an interface that is meant to be used with `@fieldparentptr` to implement the actual path logic.
pub const generatedfile = struct {
    /// the step that generates the file
    step: *step,

    /// the path to the generated file. must be either absolute or relative to the build root.
    /// this value must be set in the `fn make()` of the `step` and must not be `null` afterwards.
    path: ?[]const u8 = null,

    // ...
}
```

We will understand why `LazyPath` takes a pointer to `GeneratedFile` and what these comments mean later.

For now, let's try to express the idea that the file is generated:
```zig
const generated_file = b.allocator.create(std.Build.GeneratedFile) catch @panic("OOM");
generated_file.* = .{
    .step = &nasm.step,
    .path = "src/example.bin",
};

exe_mod.addAnonymousImport("example", .{
    .root_source_file = .{ .generated = .{
        .file = generated_file,
    } },
});

// Explicit step dependency can be removed now.
// exe.step.dependOn(&nasm.step);
```

We allocate[^panic-OOM] a `GeneratedFile`, say that `src/example.bin` is a file generated by the `nasm` step, and that the root source file of the module is the generated file.

[^panic-OOM]: `catch @panic("OOM")` is a common pattern in the Zig build system because running out of memory is not a use case the system is designed for, and there is no better way of recovery than to abort.

The build script will correctly handle recompilation of the binary on changes to the assembly file even without the explicit dependency on the `nasm` step. But this dependency should have been figured out anyway because of our use of `GeneratedFile`, right?

Let's verify that it is indeed the case. We add the following line to the end of the build script:
```zig
std.debug.print("{any}\n", .{exe.step.dependencies.items});
```
...and run:
```shell
$ zig build
{  }
```

Wait... What?..

### Where module dependencies are resolved

So, we know that we can't declare step dependencies during the make phase, so it can't be in the `make` function, but at the same time, these dependencies aren't declared at the end of our configuration logic. What is going on?

Let's hook a debugger and see!

If we replace the debug print line with the `@breakpoint` built-in:
```zig
// std.debug.print("{any}\n", .{exe.step.dependencies.items});
@breakpoint();
```
...and run the build script, it will crash and the `zig` binary will give us the failed command:
```shell
$ zig build
error: the following build command crashed:
/home/sp/bla/zig-embed-example/.zig-cache/o/92c4013cb4046f78a0d9b2ba466b6c47/build /home/sp/zig-installs/zig-x86_64-linux-0.14.1/zig /home/sp/zig-installs/zig-x86_64-linux-0.14.1/lib /home/sp/bla/zig-embed-example /home/sp/bla/zig-embed-example/.zig-cache /home/sp/.cache/zig --seed 0x71792baa -Z6225a30f836b0f73
```

We can run this command under a debugger, and it will stop at the line with the `@breakpoint` built-in:
```shell
$ gdb -ex "r" --args /home/sp/bla/zig-embed-example/.zig-cache/o/92c4013cb4046f78a0d9b2ba466b6c47/build /home/sp/zig-installs/zig-x86_64-linux-0.14.1/zig /home/sp/zig-installs/zig-x86_64-linux-0.14.1/lib /home/sp/bla/zig-embed-example /home/sp/bla/zig-embed-example/.zig-cache /home/sp/.cache/zig --seed 0x71792baa -Z6225a30f836b0f73
Thread 1 "build" received signal SIGTRAP, Trace/breakpoint trap.
0x000000000149d539 in build.build (b=0x7ffff7ff4410)
    at build.zig:47
47          @breakpoint();
```

Let's set a `watch` and monitor when the dependencies array changes:
```shell
(gdb) set $exe_step = &exe->step
(gdb) watch $exe_step->dependencies
Watchpoint 1: $exe_step->dependencies
(gdb) c
Continuing.
Configure
Thread 1 "build" hit Watchpoint 1: $exe_step->dependencies

Old value = ...
New value = ...
array_list.ArrayListAligned(*Build.Step,null).ensureTotalCapacityPrecise (self=0x7ffff7ff0870, new_capacity=16)
    at /home/sp/zig-installs/zig-x86_64-linux-0.14.1/lib/std/array_list.zig:478
478                     self.capacity = new_memory.len;
```

From there we can walk the stack up until we discover a familiar source file:
```shell
(gdb) up
...
(gdb) info frame
Stack level 6, frame at 0x7fffffffb6c0:
 rip = 0x149d94a
    in build_runner.createModuleDependenciesForStep
    (/home/sp/zig-installs/zig-x86_64-linux-0.14.1/lib/compiler/build_runner.zig:1486);
...
```

So, in the build runner there is the following snippet:
```zig
{
    var prog_node = main_progress_node.start("Configure", 0);
    defer prog_node.end();
    try builder.runBuild(root);
    createModuleDependencies(builder) catch @panic("OOM");
}
```

Let's break it down:
- `main_progress_node` refers to the `std.Progress` API, which is responsible for nicely displaying the build progress when we run `zig build`.
- `try builder.runBuild(root)` runs the `build` function from `build.zig`, which is exposed to the build runner under the `root` module. And this `builder` is the instance of `std.Build` that you get access to in the `build` function.
- `createModuleDependencies` is a function that calls `createModuleDependenciesForStep` for each top-level step and, thus, recursively discovers the whole graph of dependencies between modules.

I have a vague idea why it has been implemented this way. The problem is the ability to add module imports dynamically. `Compile.create` could gather all the dependency steps of its `root_module` and its imports, but what should happen when `addImport` is called on a module somewhere deep after the compile step has been created? It would need to find all the dependent modules and traverse the dependency graph backwards until it finds and updates all the transitive `Compile` steps. Sounds more complicated than simply doing a single traversal after all steps and imports have been declared. The implemented solution makes `std.Build.Step.Compile` somewhat special, however. It means that a user can't reimplement the same interface as easily. There is definitely a trade-off.

### A proper fix

Phew... We seem to have solved the problem with dependency tracking for generated files and wandered quite deep in the guts of the Zig build system, but other problems remain. In particular, the generated artifact ends up in the source tree, and we want to avoid that.

Let's start with the solution right away, and then figure out how it works:
```zig
const nasm = b.addSystemCommand(&.{ "nasm", "-fbin", "src/example.asm", "-o" });
const example_bin_path = nasm.addOutputFileArg("example.bin");

exe_mod.addAnonymousImport("example", .{
    .root_source_file = example_bin_path,
});
```

Let's test it. The listing has the following contents:
```nasm
bits 64
add rax, 5
```

If we run the program, it works:
```shell
$ zig build run | xxd -r -p | ndisasm -b 64 -
00000000  4883C005          add rax,byte +0x5
```

And if we update the listing to:
```nasm
bits 64
add rax, 6
```

...and run:
```shell
$ zig build run | xxd -r -p | ndisasm -b 64 -
00000000  4883C005          add rax,byte +0x5
```

Wait... What on Earth this time?

For some reason, after we told the build system about the output, `nasm` doesn't seem to be executed on each build script run anymore.

We can verify this with `strace`:
```shell
$ strace -s 4096 -f -e execve zig build 2>&1 | grep execve
execve("/home/sp/zig-installs/zig-current/zig", ["zig", "build"], 0x7ffecd8a1d20 /* 41 vars */) = 0
[pid 980056] execve("/home/sp/bla/zig-embed-example/.zig-cache/o/5170e68520c5838da6c58f86140437fe/build", ["/home/sp/bla/zig-embed-example/.zig-cache/o/5170e68520c5838da6c58f86140437fe/build", "/home/sp/zig-installs/zig-x86_64-linux-0.14.1/zig", "/home/sp/zig-installs/zig-x86_64-linux-0.14.1/lib", "/home/sp/bla/zig-embed-example", "/home/sp/bla/zig-embed-example/.zig-cache", "/home/sp/.cache/zig", "--seed", "0x6fe11246", "-Z8aac16b7b94b5794"], 0x7fbc6a825570 /* 41 vars */) = 0
[pid 980089] execve("/home/sp/zig-installs/zig-x86_64-linux-0.14.1/zig", ["/home/sp/zig-installs/zig-x86_64-linux-0.14.1/zig", "build-exe", "-ODebug", "--dep", "example", "-Mroot=/home/sp/bla/zig-embed-example/src/main.zig", "-Mexample=/home/sp/bla/zig-embed-example/.zig-cache/o/099fc0e8ca714f2aafddb8e206ac025b/example.bin", "--cache-dir", "/home/sp/bla/zig-embed-example/.zig-cache", "--global-cache-dir", "/home/sp/.cache/zig", "--name", "embed-example", "--zig-lib-dir", "/home/sp/zig-installs/zig-x86_64-linux-0.14.1/lib/", "--listen=-"], 0x7f9e4f606850 /* 42 vars */) = 0
```

So, we see no calls to `nasm` in-between calls to the build runner and the `zig` compiler.

Let's test with a more evident command that declaring an output file argument changes the behavior. We add the following to the build script:
```zig
const echo = b.addSystemCommand(&.{ "echo", "All your codebase are belong to us" });

nasm.step.dependOn(&echo.step);
```

If we run it, we see that the command is executed each time:
```shell
$ zig build
All your codebase are belong to us
$ zig build
All your codebase are belong to us
$ zig build
All your codebase are belong to us
```

But what happens when we declare an output file argument?
```zig
_ = echo.addOutputFileArg("some-file");
```

And, we don't see any output, even on the fresh run:
```shell
$ rm -rf .zig-cache
$ zig build
$ zig build
$ zig build
```

Let's dive in:
```shell
$ rm -rf .zig-cache

$ strace -s 4096 -f -e execve zig build 2>&1 | grep execve
execve("/home/sp/zig-installs/zig-current/zig", ["zig", "build"], 0x7ffd8900a990 /* 41 vars */) = 0
... many attempts to find echo on PATH
[pid 985343] execve("/bin/echo", ["echo", "All your codebase are belong to us", "/home/sp/bla/zig-embed-example/.zig-cache/o/f1c6ee44bca29ed04bec4f4b00531342/some-file"], 0x7fe655218170 /* 42 vars */) = 0
... many attempts to find nasm on PATH
[pid 985344] execve("/usr/bin/nasm", ["nasm", "-fbin", "src/example.asm", "-o", "/home/sp/bla/zig-embed-example/.zig-cache/o/099fc0e8ca714f2aafddb8e206ac025b/example.bin"], 0x7fe655218370 /* 42 vars */) = 0
[pid 985345] execve("/home/sp/zig-installs/zig-x86_64-linux-0.14.1/zig", ["/home/sp/zig-installs/zig-x86_64-linux-0.14.1/zig", "build-exe", "-ODebug", "--dep", "example", "-Mroot=/home/sp/bla/zig-embed-example/src/main.zig", "-Mexample=/home/sp/bla/zig-embed-example/.zig-cache/o/099fc0e8ca714f2aafddb8e206ac025b/example.bin", "--cache-dir", "/home/sp/bla/zig-embed-example/.zig-cache", "--global-cache-dir", "/home/sp/.cache/zig", "--name", "embed-example", "--zig-lib-dir", "/home/sp/zig-installs/zig-x86_64-linux-0.14.1/lib/", "--listen=-"], 0x7fe655218a70 /* 42 vars */) = 0
[pid 985383] execve("/home/sp/zig-installs/zig-x86_64-linux-0.14.1/zig", ["/home/sp/zig-installs/zig-x86_64-linux-0.14.1/zig", "ld.lld", "--error-limit=0", "-mllvm", "-float-abi=hard", "--entry", "_start", "-z", "stack-size=16777216", "--build-id=none", "--image-base=16777216", "--eh-frame-hdr", "-znow", "-m", "elf_x86_64", "-static", "-o", "/home/sp/bla/zig-embed-example/.zig-cache/o/4abcde2e42e7a33a51113a88733e6d92/embed-example", "/home/sp/bla/zig-embed-example/.zig-cache/o/4abcde2e42e7a33a51113a88733e6d92/embed-example.o", "--as-needed", "/home/sp/.cache/zig/o/d2199b08aa4ce39689e3206c819a32d3/libcompiler_rt.a"], 0x7f9e44684f40 /* 42 vars */) = 0

$ strace -s 4096 -f -e execve zig build 2>&1 | grep execve
execve("/home/sp/zig-installs/zig-current/zig", ["zig", "build"], 0x7ffd9ffcbda0 /* 41 vars */) = 0
[pid 985704] execve("/home/sp/bla/zig-embed-example/.zig-cache/o/5b6cb24362f4401ec01e9418a3b72204/build", ["/home/sp/bla/zig-embed-example/.zig-cache/o/5b6cb24362f4401ec01e9418a3b72204/build", "/home/sp/zig-installs/zig-x86_64-linux-0.14.1/zig", "/home/sp/zig-installs/zig-x86_64-linux-0.14.1/lib", "/home/sp/bla/zig-embed-example", "/home/sp/bla/zig-embed-example/.zig-cache", "/home/sp/.cache/zig", "--seed", "0x3a2edbfa", "-Zad6c786ef62de824"], 0x7fc1cc500570 /* 41 vars */) = 0
[pid 985737] execve("/home/sp/zig-installs/zig-x86_64-linux-0.14.1/zig", ["/home/sp/zig-installs/zig-x86_64-linux-0.14.1/zig", "build-exe", "-ODebug", "--dep", "example", "-Mroot=/home/sp/bla/zig-embed-example/src/main.zig", "-Mexample=/home/sp/bla/zig-embed-example/.zig-cache/o/099fc0e8ca714f2aafddb8e206ac025b/example.bin", "--cache-dir", "/home/sp/bla/zig-embed-example/.zig-cache", "--global-cache-dir", "/home/sp/.cache/zig", "--name", "embed-example", "--zig-lib-dir", "/home/sp/zig-installs/zig-x86_64-linux-0.14.1/lib/", "--listen=-"], 0x7f8a102bca30 /* 42 vars */) =
```

On the fresh run, we actually see a call to `echo`, but there is no output; and on the second run, when the cache is populated, `echo` is not executed.

The following logic in the `std.Build.Step.Run.make` is responsible for the caching behavior:
```zig
const run: *Run = @fieldParentPtr("step", step);
const has_side_effects = run.hasSideEffects();

// ...

if (!has_side_effects and try step.cacheHitAndWatch(&man)) {
    // cache hit, skip running command
    // ...
```

What is this curious `hasSideEffects()`? Let's hook some debug prints and run:
```zig
const run: *Run = @fieldParentPtr("step", step);
const has_side_effects = run.hasSideEffects();

// ...

std.debug.print("cmd {s} side effects: {any}\n", .{ run.argv.items[0].bytes, has_side_effects });

if (!has_side_effects and try step.cacheHitAndWatch(&man)) {
    std.debug.print("cmd {s} cache hit\n", .{run.argv.items[0].bytes});

    // cache hit, skip running command
    // ...
```

```shell
$ zig build
cmd echo side effects: false
cmd echo cache hit
cmd nasm side effects: false
cmd nasm cache hit
```

If we disable declaring an output file argument and run it twice:
```shell
$ zig build
cmd echo side effects: true
All your codebase are belong to us
cmd nasm side effects: false
cmd nasm cache hit

$ zig build
cmd echo side effects: true
All your codebase are belong to us
cmd nasm side effects: false
cmd nasm cache hit
```

We can see that the `echo` command is now considered to have side effects and its execution is never cached.

This is how the side effects detection is defined:
```zig
/// Returns whether the Run step has side effects *other than* updating the output arguments.
fn hasSideEffects(run: Run) bool {
    if (run.has_side_effects) return true;
    return switch (run.stdio) {
        .infer_from_args => !run.hasAnyOutputArgs(),
        .inherit => true,
        .check => false,
        .zig_test => false,
    };
}
```

By default, `run.stdio` is `.infer_from_args`, and this is true in our case, and its documentation describes exactly the behavior we observed:
```zig
pub const StdIo = union(enum) {
    /// Whether the Run step has side-effects will be determined by whether or not one
    /// of the args is an output file (added with `addOutputFileArg`).
    /// If the Run step is determined to have side-effects, this is the same as `inherit`.
    /// The step will fail if the subprocess crashes or returns a non-zero exit code.
    infer_from_args,

    // ...
```

There are other options, so check them out if you want to know how to affect this logic.

In essence, if a command has output file arguments, it is considered to be a deterministic code generator and, thus, if its inputs don't change, we don't need to rerun the command, and we can use the cached result. What's more, the build system thinks that the inputs don't change even when we modify `src/example.asm` because the build system doesn't know that argument `src/example.asm` is a file path and, thus, won't check the contents of the file.

What about the other strange observation? Where does the output go on the first run, when nothing is cached and the command is actually executed?

Somewhere deep there is a method `std.Build.Step.run.spawnChildAndCollect` which has the following logic:
```zig
child.stdin_behavior = switch (run.stdio) {
    .infer_from_args => if (has_side_effects) .Inherit else .Ignore,
    .inherit => .Inherit,
    .check => .Ignore,
    .zig_test => .Pipe,
};
child.stdout_behavior = switch (run.stdio) {
    .infer_from_args => if (has_side_effects) .Inherit else .Ignore,
    .inherit => .Inherit,
    .check => |checks| if (checksContainStdout(checks.items)) .Pipe else .Ignore,
    .zig_test => .Pipe,
};
child.stderr_behavior = switch (run.stdio) {
    .infer_from_args => if (has_side_effects) .Inherit else .Pipe,
    .inherit => .Inherit,
    .check => .Pipe,
    .zig_test => .Pipe,
};
```

Based on the same side effects logic, the `Run` step chooses to ignore the output of the command. This is why we haven't seen anything in the terminal, despite the fact that the command was executed.

### Back to the main line

It is nice that the build system is able to cache the results of commands. We can run pretty expensive code generation and be sure that the build system won't be wasteful. But what should we do with the `nasm` step to make it aware of the contents of `src/example.asm`?

The fix is very simple:
```zig
const nasm = b.addSystemCommand(&.{ "nasm", "-fbin", "-o" });
const example_bin_path = nasm.addOutputFileArg("example.bin");
nasm.addFileArg(b.path("src/example.asm"));
```

We tell the build system explicitly that there is an argument which is a file. As you might have guessed, you can pass `LazyPath`s to other generated files here, and everything will work out. Magic, isn't it?

Let's test that it finally functions:

{% include code-filename.html file="src/example.asm" %}
```
bits 64
add rax, 5
```

```shell
$ zig build run | xxd -r -p | ndisasm -b 64 -
00000000  4883C005          add rax,byte +0x5
```

{% include code-filename.html file="src/example.asm" %}
```
bits 64
add rax, 6
```

```shell
$ zig build run | xxd -r -p | ndisasm -b 64 -
00000000  4883C006          add rax,byte +0x6
```

Cool. We got it working, the solution is clean, and we can verify with `strace` that `example.bin` is placed somewhere in `.zig-cache` and not in the source tree by examining with `strace` the `-Mexample` argument to `zig build-exe`, which tells where to find the `example` module:
```
-Mexample=/home/sp/bla/zig-embed-example/.zig-cache/o/9460d422afbe77dba6d523670efb111e/example.bin
```

But... don't you have the same nudging feeling?.. How does this work?..

### The Zig Build Cache System

By default, the local cache for a project lives at `.zig-cache`, relative to the root of the project. This directory has several subdirectories where `.zig-cache/o` is the most intresting for now.

Each cache entry is a directory at a path of the form `.zig-cache/o/<hash>/`. This hash is the hash of everything a step depends on: all its settings, arguments, flags, environment variables, input files and their contents, etc. When the `make` function of a step is run, it computes this hash from its input and, if there is a subdirectory of `.zig-cache/o/` with such a name, it's a cache hit.

The hash-named subdirectory will contain all the artifacts the step will produce. For the `Run` step that executes `nasm`, it is where the generated `example.bin` will end up. For a `Compile` step, it is where the binary or the library (and intermediate object files) will be put.

Let's check that for different contents of `src/example.asm`, we actually get different hashes. To do this, we can once again modify `std.Build.Step.Run.make`:
```zig
// ...

if (!has_side_effects and try step.cacheHitAndWatch(&man)) {
    // cache hit, skip running command
    const digest = man.final();

    std.debug.print("cmd {s} cache hit: {s}\n", .{ run.argv.items[0].bytes, digest });

    // ...
```

If we run it on different versions of `src/example.asm`:

{% include code-filename.html file="src/example.asm" %}
```
bits 64
add rax, 5
```

```shell
$ zig build
cmd nasm cache hit: 9460d422afbe77dba6d523670efb111e
```

{% include code-filename.html file="src/example.asm" %}
```
bits 64
add rax, 6
```

```shell
$ zig build
cmd nasm cache hit: 06083fc9795ca675a9a53318e5bac728
```

...we indeed get different hashes. Additionally, we can verify that the corresponding cache entries have the generated artifact:
```shell
$ cat .zig-cache/o/9460d422afbe77dba6d523670efb111e/example.bin | ndisasm -b 64 -
00000000  4883C005          add rax,byte +0x5
$ cat .zig-cache/o/06083fc9795ca675a9a53318e5bac728/example.bin | ndisasm -b 64 -
00000000  4883C006          add rax,byte +0x6
```

However, hashing the contents of all the files we depend on each time the build script is run sounds quite expensive. Especially, considering that the build system also checks if it needs to rebuild the standard library and the compiler runtime via the same cache system each time the project is built, and it is a lot of files to check and hash.

I could continue to build up the drama, but the post is already quite long, and I am running out of energy.

The way the Zig build system optimizes the hash calculation is by employing special manifest files each stored at a path of the form `.zig-cache/<hash>.txt`. There, the hash is calculated from everything the hash knows without looking into files. In the case of our `nasm` step, it is the settings, arguments, and input file paths.

A manifest file contains a list of all files the step depends on alongside with its hash, size, inode number, and modification time, which were recorded last time it was checked.

When a step wants to check if there is a cache hit, it opens up its manifest file and for each input file, compares the size, the inode number, and the modification time with what is recorded in the manifest file. If these values match, then it can be said with a high certainty that the file is the same, and the hash recorded in the manifest file is used instead of recalculating the file contents hash. If any of them differs, the file is rehashed, and the manifest file is updated with the new value.

In our case, this means that even though invocations of the `nasm` step that differ in the contents of `src/example.asm` do get a different cache entry, they share the same manifest file, which gets updated after each invocation:

{% include code-filename.html file="src/example.asm" %}
```
bits 64
add rax, 5
```

```shell
$ zig build
cmd nasm cache hit: 9460d422afbe77dba6d523670efb111e
$ cat .zig-cache/h/d1409d2439e612663d4f28c7a42144de.txt
0
19 37562985 1751837044258175244 50517e0e12920d27b774fdb95d32aea1 1 src/example.asm
```

{% include code-filename.html file="src/example.asm" %}
```
bits 64
add rax, 6
```

```shell
$ zig build
cmd nasm cache hit: 06083fc9795ca675a9a53318e5bac728
$ cat .zig-cache/h/d1409d2439e612663d4f28c7a42144de.txt
0
19 37562991 1751837080814766160 b2c031a5d72f4b464eec657f2d94ea65 1 src/example.asm
```

This is a good optimization, but the build system has to call `stat` to get the metadata on each input file, nonetheless; and there are many of these calls each time:
```shell
$ strace -f -e trace=stat,statx,lstat,fstat zig build 2>&1 | grep -E 'stat|lstat|fstat|statx' | wc -l

1722
```

Such state of affairs can be improved by the new `--watch` mode that can leverage the file system APIs to be notified about which files have changed precisely.


### Tying back

We have dived quite deeply into the internals of the build system. Let's return to what we started with and tie the last hanging threads.

As we have already found out, the cache key is calculated during the `make` phase via a complicated process. Therefore, the path at which the generated `example.bin` artifact will be put is not known during the configuration phase, when we must provide a `LazyPath` to another step.

This is where the fact that the `LazyPath` stores not a value of `GeneratedFile` but a pointer to it becomes important:
```zig
/// A reference to an existing or future path.
pub const LazyPath = union(enum) {
    // ...

    generated: struct {
        file: *const GeneratedFile,
        up: usize = 0,
        sub_path: []const u8 = "",
    },

    // ...
};

pub const GeneratedFile = struct {
    /// The step that generates the file
    step: *Step,

    /// The path to the generated file. Must be either absolute or relative to the build root.
    /// This value must be set in the `fn make()` of the `step` and must not be `null` afterwards.
    path: ?[]const u8 = null,

    // ...
}
```

Here, `addOutputFileArg` returns a `LazyPath` that stores a pointer to a `GeneratedFile` that is allocated and managed by the `nasm` step:
```zig
const nasm = b.addSystemCommand(&.{ "nasm", "-fbin", "-o" });
const example_bin_path = nasm.addOutputFileArg("example.bin");
nasm.addFileArg(b.path("src/example.asm"));
```

During `nasm`'s `make` phase, the file path becomes known, and the step writes it to the `GeneratedFile` struct. When the `make` function of the `exe` step, which uses the generated file as input, is run, the file path is already there.

## Conclusion

Despite the long journey, the final build script is very simple:

{% include code-filename.html file="build.zig" %}
```zig
const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    const nasm = b.addSystemCommand(&.{ "nasm", "-fbin", "-o" });
    const example_bin_path = nasm.addOutputFileArg("example.bin");
    nasm.addFileArg(b.path("src/example.asm"));

    const exe_mod = b.createModule(.{
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });

    exe_mod.addAnonymousImport("example", .{
        .root_source_file = example_bin_path,
    });

    const exe = b.addExecutable(.{
        .name = "embed-example",
        .root_module = exe_mod,
    });

    b.installArtifact(exe);

    const run_cmd = b.addRunArtifact(exe);

    if (b.args) |args| {
        run_cmd.addArgs(args);
    }

    run_cmd.step.dependOn(b.getInstallStep());

    const run_step = b.step("run", "Run the program");
    run_step.dependOn(&run_cmd.step);
}
```

I have really enjoyed fumbling with the Zig build system. It strikes a great balance between declarative and imperative. You declare a set of steps and their dependencies, and the build system uses that for caching, printing the help message, tracking file changes, and so on. Moreover, the Zig build system provides a solid set of built-in steps. At the same time, you are not constrained by only the use cases the developers have anticipated. You can create your own step and run arbitrary code in the `make` function.

While trying to solve the initial problem and in the course of writing this post, I went from an almost complete noob understanding of the Zig build system to a quite confident grasp of its internals. What surprised me the most is how readable the sources of the build system and the standard library are[^std-readability] and how hackable the build system, the standard library, and the Zig compiler itself are. I could easily obtain the command for the build runner (though, I'd like the process to be even more streamlined) and launch it under a debugger.

Zig made a very interesting choice: it moved all the compiler magic into explicit `@builtin`s which means that the standard library doesn't have any magic in it. It is just an ordinary library[^zig-std-powerless] which is built with the same compiler and goes through the same cache system. This has several advantages:
- The standard library (and the rest of the build system) is checked in the cache and gets rebuilt if any of the files change each time you run `zig build-exe` (or others) either directly or indirectly via `zig build`. This allows you to hack the standard library and get instant results in our current project. How cool is that?
- In debug mode, the standard library is also built in debug mode with debug symbols on, which makes it possible to step into the standard library in the debugger (hello, Rust).
- Cross-compilation becomes easy, too. There doesn't have to be a precompiled distribution of the standard library for every supported target. Under whatever target Zig can compile, relevant bits of `std` will be available.

I could even clone the `zig` repo and build the debug version of the compiler with a plain `zig built` in a matter of *minutes*. I could then use my version of the Zig compiler (with e.g. debug logs enabled) in the build system. Mindblowing. Though, I found ways to test and exihibit all the behaviors described in this post without going that far.

[^std-readability]: Zig is a new language and it hasn't reached a stable version yet so it can afford introducing breaking changes and keeping the code in a clean state, and I'm glad it does. Backwards compatibility concerns can mess the code, and you can already see traces of this deterioration in the Rust standard library. However, they are very careful with it and the code quality there is still very high. If you ever took a look at the sources of the C++ standard library in any of the major compilers, you know how bad things can get.

[^zig-std-powerless]: Thanks [matklad](https://matklad.github.io/2025/03/19/comptime-zig-orm.html) for the insight.

What could be done better? Documentation. The info on the build system is scattered across blog posts, videos, and existing projects with varying degrees of how correctly they use the build system. Even though there are some quality materials, I still had to discover many things the hard way. A solid reference with a cookbook maintained by the Zig project would be of great help to get started faster.

