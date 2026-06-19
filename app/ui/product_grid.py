import flet as ft


def grid_view(page: ft.Page, state):

    def _edit_product(sku):
        page.go(f"/detail/{sku}")

    product_cards = []
    for prod in state.products:
        total = len(prod.images)
        status_color = {
            "Pendiente": ft.Colors.GREY,
            "IA_OK": ft.Colors.GREEN,
            "Editado": ft.Colors.ORANGE,
            "Subido": ft.Colors.BLUE,
            "Error": ft.Colors.RED,
        }.get(prod.estado, ft.Colors.GREY)

        card = ft.Container(
            content=ft.Row([
                ft.Column([
                    ft.Text(prod.sku, weight=ft.FontWeight.BOLD, size=16),
                    ft.Text(f"{total} imagen{'es' if total != 1 else ''}",
                            size=12, color=ft.Colors.GREY_600),
                ], spacing=2, width=220),
                ft.Container(
                    content=ft.Column([
                        ft.Text(prod.preview_titulo[:50],
                                size=13, no_wrap=True,
                                overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(prod.color or "—", size=12,
                                color=ft.Colors.GREY_600),
                    ], spacing=2),
                    expand=True,
                ),
                ft.Container(
                    content=ft.Text(prod.estado, size=12,
                                    color=status_color),
                    width=100, alignment=ft.alignment.center,
                ),
                ft.Row([
                    ft.IconButton(
                        ft.Icons.AUTO_AWESOME,
                        tooltip="Generar con IA",
                        data=prod.sku,
                    ),
                    ft.IconButton(
                        ft.Icons.EDIT,
                        tooltip="Editar",
                        data=prod.sku,
                        on_click=lambda e, s=prod.sku: _edit_product(s),
                    ),
                ]),
            ]),
            padding=ft.padding.all(12),
            border=ft.border.all(1, ft.Colors.GREY_300),
            border_radius=8,
            bgcolor=ft.Colors.WHITE,
            ink=True,
            on_click=lambda e, s=prod.sku: _edit_product(s),
        )
        product_cards.append(card)

    view = ft.View(
        route="/grid",
        appbar=ft.AppBar(
            title=ft.Text(f"Productos ({len(state.products)})"),
            bgcolor=ft.Colors.BLUE_700,
            color=ft.Colors.WHITE,
            leading=ft.IconButton(
                ft.Icons.ARROW_BACK,
                on_click=lambda _: page.go("/"),
            ),
        ),
        controls=[
            ft.Container(
                content=ft.Column(
                    [ft.ListView(controls=product_cards, spacing=6,
                                 expand=True)],
                    expand=True,
                ),
                padding=ft.padding.all(16),
                expand=True,
            ),
        ],
        floating_action_button=ft.FloatingActionButton(
            text="Generar todo",
            icon=ft.Icons.AUTO_AWESOME,
            on_click=lambda e: None,
            disabled=True,
        ),
    )
    return view
