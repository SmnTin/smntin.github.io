---
layout: default
title: Home
---

<img align="right" width="200" style="margin-left: 20px" src="assets/my-photo.jpeg">
Ffjnf sgvjsekfnk jesnfknsekj fneskjnfkjse fsenfkljsenkfn jkfnsenfk fekfnejknf fkjenkfnekjnf nfjkenfne nfkjenfe nfkenkfne kjfneknf nfeknfke kfneknfken kenfkenfke. Ffjnf sgvjsekfnk jesnfknsekj fneskjnfkjse fsenfkljsenkfn jkfnsenfk fekfnejknf fkjenkfnekjnf nfjkenfne nfkjenfe nfkenkfne kjfneknf nfeknfke kfneknfken kenfkenfke. Ffjnf sgvjsekfnk jesnfknsekj fneskjnfkjse fsenfkljsenkfn jkfnsenfk fekfnejknf fkjenkfnekjnf nfjkenfne nfkjenfe nfkenkfne kjfneknf nfeknfke kfneknfken kenfkenfke.

Ffjnf sgvjsekfnk jesnfknsekj fneskjnfkjse fsenfkljsenkfn jkfnsenfk fekfnejknf fkjenkfnekjnf nfjkenfne nfkjenfe nfkenkfne kjfneknf nfeknfke kfneknfken kenfkenfke.

# Projects

{% for project in site.projects %}

### [{{ project.title }}]({{ project.github }})

{{ project.content | markdownify }}

{% endfor %}