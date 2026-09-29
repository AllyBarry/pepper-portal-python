# -*- coding: utf-8 -*-
"""
What Pepper's tablet can show. Each kind knows how to put itself on a
robot.tablet.TabletDisplay; adding a kind means adding a class and listing it
in KINDS -- the routes don't change.

    landing  the RAIL Lab page served by this portal (/tablet)
    video    a video in media/, streamed from the Jetson to the native player
    image    an image in media/
    web      any http(s) URL -- a website works because Pepper has internet
             through the Jetson's NAT
"""
try:
    from urllib import quote            # Py2
except ImportError:                     # pragma: no cover
    from urllib.parse import quote      # Py3


def _media_url(base_url, rel):
    return base_url + "/media/" + "/".join(quote(part) for part in rel.split("/"))


class TabletContent(object):
    kind = None

    def __init__(self, ref, label=None):
        self.ref = ref
        self.label = label or ref

    def url(self, base_url):
        raise NotImplementedError

    def render(self, tablet, base_url):
        """Show this on the tablet; returns the URL it loaded."""
        raise NotImplementedError

    def describe(self):
        return {"kind": self.kind, "ref": self.ref, "label": self.label}


class LandingPage(TabletContent):
    kind = "landing"
    PATH = "/tablet"

    def __init__(self, ref="rail-lab", label="RAIL Lab landing page"):
        super(LandingPage, self).__init__(ref, label)

    def url(self, base_url):
        return base_url + self.PATH

    def render(self, tablet, base_url):
        url = self.url(base_url)
        tablet.show_url(url)
        return url


class MediaVideo(TabletContent):
    kind = "video"

    def url(self, base_url):
        return _media_url(base_url, self.ref)

    def render(self, tablet, base_url):
        url = self.url(base_url)
        tablet.play_video(url)
        return url


class MediaImage(TabletContent):
    kind = "image"

    def url(self, base_url):
        return _media_url(base_url, self.ref)

    def render(self, tablet, base_url):
        url = self.url(base_url)
        tablet.show_image(url)
        return url


class WebPage(TabletContent):
    kind = "web"

    def __init__(self, ref, label=None):
        ref = (ref or "").strip()
        if not (ref.startswith("http://") or ref.startswith("https://")):
            raise ValueError("Website address must start with http:// or https://")
        super(WebPage, self).__init__(ref, label)

    def url(self, base_url):
        return self.ref

    def render(self, tablet, base_url):
        tablet.show_url(self.ref)
        return self.ref


KINDS = dict((cls.kind, cls) for cls in (LandingPage, MediaVideo, MediaImage, WebPage))
_MEDIA_KINDS = {"video": MediaVideo, "image": MediaImage}


def from_choice(kind, ref, media_exists):
    """
    Build content from a portal choice. media_exists(rel) -> bool guards media
    kinds, so only files actually in media/ can be shown.
    """
    cls = KINDS.get(kind)
    if cls is None:
        raise ValueError("Unknown tablet content kind: %r" % (kind,))
    if cls is LandingPage:
        return LandingPage()
    if kind in _MEDIA_KINDS and not media_exists(ref or ""):
        raise ValueError("%s is not in media/" % ref)
    return cls(ref)


def catalog(media_files):
    """
    Everything the portal offers to show: the landing page plus each video
    and image in media/ (dicts from media_store.status()["files"]).
    """
    items = [LandingPage()]
    for f in media_files:
        if not f.get("managed"):
            continue
        cls = _MEDIA_KINDS.get(f.get("kind"))
        if cls is not None:
            items.append(cls(f["path"], f["path"]))
    return [item.describe() for item in items]
