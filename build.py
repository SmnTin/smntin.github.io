import jinja2
import os
import shutil
import mistune
import mistune.directives
import frontmatter
import pygments
import pygments.formatters.html
import pygments.lexers
import re
from datetime import date

dest_dir_name = "dest"
site_title = "SmnTin's Bay"
site_url = "https://smntin.dev"


def build():
    # Prepare dest.
    shutil.rmtree(dest_dir_name, ignore_errors=True)
    os.mkdir(dest_dir_name)

    # Write assets.
    shutil.copytree("assets", os.path.join(dest_dir_name, "assets"))

    pygments_formatter = pygments.formatters.html.HtmlFormatter(style="github-dark", wrapcode=True)

    with open(os.path.join(dest_dir_name, "assets", "pygments.css"), "w") as f:
        f.write(pygments_formatter.get_style_defs(".highlight"))

    # Rendering common.
    jinja_env = jinja2.Environment(loader=jinja2.loaders.FileSystemLoader("templates"))

    def render_page(template_name, path_in_dest, **kwargs):
        template = jinja_env.get_template(template_name)
        path = os.path.join(dest_dir_name, path_in_dest)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(
                template.render(
                    site={
                        "title": site_title,
                        "url": site_url,
                    },
                    **kwargs,
                )
            )

    # Render posts.
    class MistuneRenderer(mistune.HTMLRenderer):
        def block_code(self, code, info=None):
            pygments_lexer = None
            lexer_name = None
            filename = None
            if info is not None:
                parts = info.split()
                if len(parts) > 0:
                    lexer_name = parts[0]
                if len(parts) > 1:
                    filename = parts[1]

            if lexer_name is not None:
                try:
                    pygments_lexer = pygments.lexers.get_lexer_by_name(lexer_name, stripall=True)
                except pygments.util.ClassNotFound:
                    pass
            if pygments_lexer is None:
                pygments_lexer = pygments.lexers.get_lexer_by_name("text", stripall=True)
            highlighted = pygments.highlight(code, pygments_lexer, pygments_formatter)

            if filename is not None:
                return f'<figure class="codeblock"><figcaption>{filename}</figcaption>{highlighted}</figure>'
            else:
                return highlighted

        def heading(self, text, level, **attrs):
            slug = re.sub(r"[^\w]+", "-", text.strip().lower()).strip("-")
            return f'<h{level} id="{slug}">{text}</h{level}>\n'

        def image(self, alt, url, title=None):
            if title:
                return f'<figure class="img-figure"><img src="{url}" alt="{alt}"><figcaption>{title}</figcaption></figure>'
            return f'<img src="{url}" alt="{alt}">'

    md = mistune.create_markdown(
        renderer=MistuneRenderer(),
        plugins=[
            "table",
            "footnotes",
            "strikethrough",
            "superscript",
            "subscript",
            mistune.directives.FencedDirective([mistune.directives.Image()]),
        ],
    )

    posts = []
    posts_dir_name = "posts"
    for post_file_name in os.listdir(posts_dir_name):
        post_file_path = os.path.join(posts_dir_name, post_file_name)

        if not post_file_name.startswith("_") and post_file_name.endswith(".md"):
            # For example, "2026-02-01-some-post.md".
            post_file_name_parts = post_file_name.split("-", maxsplit=3)
            post_year, post_month, post_day, post_name = post_file_name_parts
            post_year, post_month, post_day = (
                int(post_year),
                int(post_month),
                int(post_day),
            )
            post_name = post_name.removesuffix(".md")
            post_date = date(post_year, post_month, post_day)

            post = frontmatter.load(post_file_path)
            post_meta = post.metadata
            post_html = md(post.content)

            post_title = post_meta["title"]
            post_url_rel = f"/blog/{post_year}/{post_name}/"
            post_update_date = post_meta.get("updated")

            render_page(
                "post.html",
                os.path.join(post_url_rel.removeprefix("/"), "index.html"),
                post={
                    "title": post_title,
                    "date": post_date,
                    "content": post_html,
                },
            )

            post_url_abs = f"{site_url}{post_url_rel}"

            posts.append(
                {
                    "title": post_title,
                    "date": post_date,
                    "update_date": post_update_date,
                    "url_rel": post_url_rel,
                    "url_abs": post_url_abs,
                    "content": post_html,
                }
            )

    posts.sort(key=lambda post: post["date"], reverse=True)
    posts_update_date = max(
        [post["update_date"] for post in posts if post["update_date"] is not None],
        default=posts[0]["date"],
    )

    # Render other pages.
    render_page("blog.html", "blog/index.html", posts=posts)
    render_page("index.html", "index.html")

    render_page("atom.xml", "atom.xml", posts=posts, posts_update_date=posts_update_date)


if __name__ == "__main__":
    build()
