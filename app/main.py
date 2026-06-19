import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import flet as ft

from app.state import AppState
from app.ui.home import home_view
from app.ui.product_grid import grid_view
from app.ui.product_detail import detail_view


def main(page: ft.Page):
    page.title = "ShowSport Upload Manager"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0
    page.window.width = 1200
    page.window.height = 800
    page.window.center()

    app_state = AppState()

    def route_change(e):
        page.views.clear()

        if page.route == "/":
            page.views.append(home_view(page, app_state))
        elif page.route == "/grid":
            page.views.append(grid_view(page, app_state))
        elif page.route.startswith("/detail/"):
            sku = page.route.split("/detail/", 1)[1]
            page.views.append(detail_view(page, app_state, sku))
        else:
            page.go("/")
            return

        page.update()

    def view_pop(e):
        page.views.pop()
        top = page.views[-1]
        page.go(top.route)

    page.on_route_change = route_change
    page.on_view_pop = view_pop
    page.go("/")


if __name__ == "__main__":
    ft.app(target=main, host="127.0.0.1", port=5050)
