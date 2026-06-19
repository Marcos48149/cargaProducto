import threading
import flet as ft


def grid_view(page: ft.Page, state):

    def _edit_product(sku):
        page.go(f"/detail/{sku}")

    def _generate_single(prod):
        dlg = ft.AlertDialog(
            title=ft.Text(f"Generando para {prod.sku}..."),
            content=ft.Column([
                ft.ProgressBar(),
                ft.Text("Web search + GPT-4o, puede tomar unos segundos",
                        size=12),
            ], tight=True, spacing=10),
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

        def _run():
            try:
                from app.core.product_pipeline import generate_product
                datos = generate_product(prod.sku, prod.images)
                if datos:
                    _apply_data(prod, datos)
            except Exception:
                prod.estado = "Error"
            dlg.open = False
            page.go("/grid")  # Refresh

        threading.Thread(target=_run, daemon=True).start()

    def _generate_all():
        pendientes = [p for p in state.products
                      if p.estado in ("Pendiente", "Error")]
        if not pendientes:
            return

        dlg = ft.AlertDialog(
            title=ft.Text("Generando todos..."),
            content=ft.Column([
                ft.ProgressBar(),
                ft.Text("Procesando productos...", size=12),
            ], tight=True, spacing=10),
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

        def _run_all():
            from app.core.product_pipeline import generate_product
            for prod in pendientes:
                try:
                    datos = generate_product(prod.sku, prod.images)
                    if datos:
                        _apply_data(prod, datos)
                except Exception:
                    prod.estado = "Error"
            dlg.open = False
            page.go("/grid")  # Refresh

        threading.Thread(target=_run_all, daemon=True).start()

    def _apply_data(prod, datos):
        prod.titulo = datos.get('titulo')
        prod.descripcion = datos.get('descripcion')
        prod.color = datos.get('color')
        prod.categoria = datos.get('categoria')
        prod.genero = datos.get('genero')
        prod.talles = datos.get('talles', [])
        prod.palabras_clave = datos.get('palabras_clave')
        prod.url_slug = datos.get('url_slug')
        try:
            prod.precio = float(datos.get('precio', 0))
        except (ValueError, TypeError):
            prod.precio = 0
        prod.estado = "IA_OK"

    # ── Build cards ──
    product_cards = []
    for prod in state.products:
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
                    ft.Text(
                        f"{len(prod.images)} imagen{'es' if len(prod.images) != 1 else ''}",
                        size=12, color=ft.Colors.GREY_600),
                ], spacing=2, width=220),
                ft.Container(
                    content=ft.Column([
                        ft.Text(
                            (prod.titulo or prod.sku)[:60],
                            size=13, no_wrap=True,
                            overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(
                            prod.color or "—", size=12,
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
                        disabled=prod.estado in ("IA_OK", "Subido"),
                        on_click=lambda e, s=prod.sku:
                            _generate_single(state.get_product(s)),
                    ),
                    ft.IconButton(
                        ft.Icons.EDIT,
                        tooltip="Editar",
                        on_click=lambda e, s=prod.sku:
                            _edit_product(s),
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
            actions=[
                ft.TextButton(
                    "Subir a VTEX",
                    icon=ft.Icons.CLOUD_UPLOAD,
                    style=ft.ButtonStyle(color=ft.Colors.WHITE),
                    on_click=lambda _: page.go("/upload"),
                ),
            ],
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
            on_click=lambda e: _generate_all(),
        ),
    )
    return view
