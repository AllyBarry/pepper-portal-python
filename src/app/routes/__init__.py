# -*- coding: utf-8 -*-
"""HTTP routes, one blueprint per area. Each only translates HTTP to robot/ calls."""
from . import media_routes, network_routes, robot_routes, scene_routes, tablet_routes

BLUEPRINTS = (
    robot_routes.bp,
    scene_routes.bp,
    media_routes.bp,
    tablet_routes.bp,
    network_routes.bp,
)


def register(app):
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)
