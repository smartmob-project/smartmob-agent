# -*- coding: utf-8 -*-


from smartmob_agent import responder


def test_app_reboot(event_loop):
    with responder(event_loop):
        pass
    with responder(event_loop):
        pass
