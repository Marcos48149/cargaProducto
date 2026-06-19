import flet as ft

from app.core.image_loader import scan_folder


def home_view(page: ft.Page, state):

    existing = [c for c in page.overlay if isinstance(c, ft.FilePicker)]
    if existing:
        pick_folder = existing[0]
    else:
        pick_folder = ft.FilePicker(on_result=lambda e: _on_folder_picked(e, page, state))
        page.overlay.append(pick_folder)

    def _on_folder_picked(e, page, state):
        if e.path:
            state.folder_path = e.path
            groups = scan_folder(e.path)
            state.products.clear()
            for sku in sorted(groups.keys()):
                state.add_product(sku, groups[sku])
            page.go("/grid")

    def _pick_folder_click(e):
        pick_folder.get_directory_path()

    view = ft.View(
        route="/",
        appbar=ft.AppBar(
            title=ft.Text("ShowSport Upload Manager"),
            center_title=True,
            bgcolor=ft.Colors.BLUE_700,
            color=ft.Colors.WHITE,
        ),
        controls=[
            ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(ft.Icons.CLOUD_UPLOAD_OUTLINED, size=80,
                                color=ft.Colors.BLUE_400),
                        ft.Container(height=10),
                        ft.Text("Seleccioná una carpeta con imágenes",
                                size=24, weight=ft.FontWeight.BOLD),
                        ft.Text(
                            "Las imágenes se agruparán automáticamente por código SKU",
                            size=14, color=ft.Colors.GREY_600),
                        ft.Container(height=20),
                        ft.ElevatedButton(
                            "Seleccionar carpeta",
                            icon=ft.Icons.FOLDER_OPEN,
                            on_click=_pick_folder_click,
                            style=ft.ButtonStyle(
                                padding=ft.padding.all(20),
                                text_style=ft.TextStyle(size=16),
                            ),
                        ),
                        ft.Container(height=20),
                        ft.Text(
                            "Luego podrás revisar, editar y subir cada producto a VTEX",
                            size=12, color=ft.Colors.GREY_400),
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                expand=True,
                alignment=ft.alignment.center,
            ),
        ],
    )
    return view
