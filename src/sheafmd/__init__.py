"""sheaf: a working page for a markdown document, shared between a person and their agent.

The library API (SPEC 16). These names stay stable through 1.x; everything else in
the package is internal.

    html = sheafmd.render(path, share=True, theme=None, title=None, toc="auto",
                          max_image_width=1400, by=None, for_=None, credit=None, log=None)
    sheafmd.write_pdf(html, out)                      # raises sheafmd.PdfError
    src = sheafmd.Source(path); text, digest = src.read(); src.update(change)
    sheafmd.strip_comments(text)                      # the share copy's comment removal
    sheafmd.comments.parse(text)                      # comments and malformed
    sheafmd.load_root_config(root); sheafmd.load_theme(spec, root)
"""
from pathlib import Path

__version__ = "1.0.0"

# `render` below is the public function, and it hides the module sheafmd/render.py as
# an attribute of the package: inside the package import from it (`from .render import
# build`), never `from . import render` or `import sheafmd.render as r`.

from . import comments
from .config import ConfigError, RootConfig, load_root_config
from .pdf import PdfError, write_pdf
from .render import RenderError, UnclosedComment, render_file, strip_comments
from .source import Source, StaleError
from .theme import Theme, load_theme

__all__ = ["render", "write_pdf", "Source", "strip_comments", "comments", "load_root_config",
           "load_theme", "RootConfig", "Theme", "PdfError", "StaleError", "ConfigError",
           "RenderError", "UnclosedComment", "__version__"]


def render(path, *, share: bool = True, theme=None, title: str | None = None,
           toc: str = "auto", max_image_width: int = 1400, by: str | None = None,
           for_: str | None = None, credit: bool | None = None,
           log: list[str] | None = None) -> str:
    """The HTML of the markdown file at `path`: a share copy by default, with every
    comment removed and no script; `share=False` gives the page as the hub would serve
    it, without the hub's meta values.

    Reads the root's `.sheaf.toml` itself (`for`, `links`, `credit`, the theme). `for_`
    replaces its `for` for this render; an empty string leaves the "for" out.
    Every render-log line (`+` added, `!` warning, `-` removed), font failures
    included, is appended to `log`; without one, the warnings go to stderr."""
    return render_file(Path(path), share=share, theme=theme, title=title, toc=toc,
                       max_image_width=max_image_width, by=by, for_=for_, credit=credit,
                       log=log)
