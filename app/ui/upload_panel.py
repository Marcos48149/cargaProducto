import threading
import flet as ft


def upload_view(page: ft.Page, state):

    log_output = ft.ListView(expand=True, spacing=2, auto_scroll=True)
    status_text = ft.Text("", size=14, weight=ft.FontWeight.BOLD)
    upload_btn = ft.ElevatedButton(
        "Subir seleccionados",
        icon=ft.Icons.CLOUD_UPLOAD,
        style=ft.ButtonStyle(padding=ft.padding.all(16)),
        on_click=lambda e: None,
    )

    def log(msg):
        log_output.controls.append(ft.Text(msg, size=12, selectable=True))
        if len(log_output.controls) > 500:
            log_output.controls.pop(0)
        page.update()

    def _run_upload(selected):
        upload_btn.disabled = True
        page.update()

        def _task():
            from app.core.vtex_upload import upload_product
            ok = 0
            err = 0
            for prod in selected:
                result = upload_product(prod, log)
                if result:
                    prod.estado = "Subido"
                    ok += 1
                else:
                    prod.estado = "Error"
                    err += 1
                status_text.value = f"✅ {ok} OK | ❌ {err} errores | {ok + err}/{len(selected)}"
                page.update()

            log(f"\n{'=' * 40}")
            if err == 0:
                log(f"🎉 Todos los productos subidos correctamente")
            else:
                log(f"⚠️ {ok} subidos, {err} con errores")
            upload_btn.disabled = False
            _rebuild_selection()
            page.update()

        threading.Thread(target=_task, daemon=True).start()

    def _start_upload(e):
        selected = [
            state.get_product(sku)
            for sku, cb in checkboxes.items()
            if cb.value
        ]
        if not selected:
            log("⚠️ No hay productos seleccionados")
            return
        log(f"▶ Iniciando subida de {len(selected)} productos...\n")
        _run_upload(selected)

    checkboxes = {}

    def _rebuild_selection():
        checkboxes.clear()
        selection_col.controls.clear()
        for prod in state.products:
            if prod.estado in ("IA_OK", "Editado", "Subido", "Error"):
                cb = ft.Checkbox(
                    label=prod.sku,
                    value=prod.estado == "IA_OK",
                    disabled=prod.estado == "Subido",
                    data=prod.sku,
                )
                checkboxes[prod.sku] = cb
                selection_col.controls.append(
                    ft.Container(
                        content=ft.Row([
                            cb,
                            ft.Text(prod.titulo or prod.sku, size=12,
                                    no_wrap=True,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                    expand=True),
                            ft.Text(
                                f"[{prod.estado}]", size=11,
                                color=ft.Colors.GREEN if prod.estado == "IA_OK"
                                else ft.Colors.GREY),
                        ]),
                        padding=ft.padding.symmetric(vertical=2),
                    )
                )

    selection_col = ft.Column(spacing=2, scroll=ft.ScrollMode.AUTO)

    upload_btn.on_click = _start_upload
    _rebuild_selection()

    view = ft.View(
        route="/upload",
        appbar=ft.AppBar(
            title=ft.Text("Subir a VTEX"),
            bgcolor=ft.Colors.BLUE_700,
            color=ft.Colors.WHITE,
            leading=ft.IconButton(
                ft.Icons.ARROW_BACK,
                on_click=lambda _: page.go("/grid"),
            ),
            actions=[
                upload_btn,
            ],
        ),
        controls=[
            ft.Container(
                content=ft.ResponsiveRow([
                    ft.Column(
                        controls=[
                            ft.Text("Productos listos para subir",
                                    weight=ft.FontWeight.BOLD, size=16),
                            ft.Container(
                                content=selection_col,
                                height=300,
                                border=ft.border.all(1, ft.Colors.GREY_300),
                                border_radius=8,
                                padding=10,
                            ),
                            status_text,
                        ],
                        col={"sm": 12, "md": 4},
                        spacing=10,
                    ),
                    ft.Column(
                        controls=[
                            ft.Text("Log de subida",
                                    weight=ft.FontWeight.BOLD, size=16),
                            ft.Container(
                                content=log_output,
                                height=500,
                                border=ft.border.all(1, ft.Colors.GREY_300),
                                border_radius=8,
                                bgcolor=ft.Colors.BLACK87,
                                padding=10,
                            ),
                        ],
                        col={"sm": 12, "md": 8},
                        spacing=10,
                    ),
                ]),
                padding=ft.padding.all(20),
                expand=True,
            ),
        ],
    )
    return view
