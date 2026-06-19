import threading
import flet as ft


def _refresh_view(page, prod, titulo_f, desc_f, color_f, cat_dd,
                  gen_dd, talles_f, kw_f, slug_f, precio_f):
    titulo_f.value = prod.titulo or ""
    desc_f.value = prod.descripcion or ""
    color_f.value = prod.color or ""
    cat_dd.value = prod.categoria
    gen_dd.value = prod.genero
    talles_f.value = ", ".join(prod.talles) if prod.talles else ""
    kw_f.value = prod.palabras_clave or ""
    slug_f.value = prod.url_slug or ""
    precio_f.value = str(prod.precio) if prod.precio else ""
    page.update()


def detail_view(page: ft.Page, state, sku):

    prod = state.get_product(sku)
    if not prod:
        return ft.View(
            route=f"/detail/{sku}",
            appbar=ft.AppBar(title=ft.Text("Producto no encontrado")),
            controls=[ft.Text("Producto no encontrado")],
        )

    titulo = ft.TextField(
        label="Título", value=prod.titulo or "",
        multiline=False, expand=True,
    )
    descripcion = ft.TextField(
        label="Descripción", value=prod.descripcion or "",
        multiline=True, min_lines=4, max_lines=10, expand=True,
    )
    color = ft.TextField(
        label="Color", value=prod.color or "",
        hint_text="ej: Negro/Blanco/Rojo",
    )
    categoria = ft.Dropdown(
        label="Categoría",
        value=prod.categoria,
        options=[
            ft.dropdown.Option("zapatillas_mujer"),
            ft.dropdown.Option("zapatillas_hombre"),
            ft.dropdown.Option("zapatillas_ninos"),
            ft.dropdown.Option("botines_mujer"),
            ft.dropdown.Option("botines_hombre"),
            ft.dropdown.Option("remeras_mujer"),
            ft.dropdown.Option("remeras_hombre"),
            ft.dropdown.Option("buzos_mujer"),
            ft.dropdown.Option("buzos_hombre"),
            ft.dropdown.Option("camperas_mujer"),
            ft.dropdown.Option("camperas_hombre"),
            ft.dropdown.Option("mochilas"),
            ft.dropdown.Option("gorras"),
            ft.dropdown.Option("medias"),
            ft.dropdown.Option("ojotas"),
            ft.dropdown.Option("accesorios"),
        ],
    )
    genero = ft.Dropdown(
        label="Género",
        value=prod.genero,
        options=[
            ft.dropdown.Option("mujer"),
            ft.dropdown.Option("hombre"),
            ft.dropdown.Option("ninos"),
            ft.dropdown.Option("unisex"),
        ],
    )
    talles = ft.TextField(
        label="Talles (separados por coma)",
        value=", ".join(prod.talles) if prod.talles else "",
        hint_text="ej: 7, 7M, 8, 8M, 9",
    )
    palabras_clave = ft.TextField(
        label="Palabras clave",
        value=prod.palabras_clave or "",
        hint_text="ej: zapatillas, adidas, fabela",
    )
    url_slug = ft.TextField(
        label="URL Slug",
        value=prod.url_slug or "",
        hint_text=f"ej: zapatillas-adidas-{sku.lower()}",
    )
    precio = ft.TextField(
        label="Precio",
        value=str(prod.precio) if prod.precio else "",
        keyboard_type=ft.KeyboardType.NUMBER,
    )

    def _guardar(e):
        prod.titulo = titulo.value
        prod.descripcion = descripcion.value
        prod.color = color.value
        prod.categoria = categoria.value
        prod.genero = genero.value
        prod.talles = [t.strip() for t in talles.value.split(",")
                       if t.strip()] if talles.value else []
        prod.palabras_clave = palabras_clave.value
        prod.url_slug = url_slug.value
        try:
            prod.precio = float(precio.value) if precio.value else 0
        except ValueError:
            prod.precio = 0
        prod.estado = "Editado"
        page.go("/grid")

    def _generate_ia(e):
        dlg = ft.AlertDialog(
            title=ft.Text(f"Generando IA..."),
            content=ft.Column([
                ft.ProgressBar(),
                ft.Text("Web search + GPT-4o", size=12),
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
            except Exception:
                prod.estado = "Error"
            dlg.open = False
            _refresh_view(page, prod, titulo, descripcion, color,
                          categoria, genero, talles, palabras_clave,
                          url_slug, precio)

        threading.Thread(target=_run, daemon=True).start()

    from app.core.product_pipeline import image_to_data_url

    image_thumbnails = ft.Row(
        wrap=True,
        spacing=6,
        controls=[
            ft.Container(
                content=ft.Image(
                    src=image_to_data_url(f),
                    width=120,
                    height=120,
                    fit=ft.ImageFit.COVER,
                ),
                border_radius=6,
                border=ft.border.all(1, ft.Colors.GREY_300),
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            )
            for f in prod.images[:6]
        ],
    )
    if len(prod.images) > 6:
        image_thumbnails.controls.append(
            ft.Container(
                content=ft.Text(f"+{len(prod.images) - 6} más",
                                size=12, color=ft.Colors.GREY_600),
                width=120, height=120,
                alignment=ft.alignment.center,
                border=ft.border.all(1, ft.Colors.GREY_300),
                border_radius=6,
            )
        )

    view = ft.View(
        route=f"/detail/{sku}",
        appbar=ft.AppBar(
            title=ft.Text(sku),
            bgcolor=ft.Colors.BLUE_700,
            color=ft.Colors.WHITE,
            leading=ft.IconButton(
                ft.Icons.ARROW_BACK,
                on_click=lambda _: page.go("/grid"),
            ),
            actions=[
                ft.TextButton(
                    "Generar IA",
                    icon=ft.Icons.AUTO_AWESOME,
                    style=ft.ButtonStyle(color=ft.Colors.WHITE),
                    on_click=_generate_ia,
                ),
            ],
        ),
        controls=[
            ft.Container(
                content=ft.ResponsiveRow([
                    ft.Column(
                        controls=[
                            ft.Text("Imágenes",
                                    weight=ft.FontWeight.BOLD, size=16),
                            image_thumbnails,
                            ft.Container(height=10),
                            ft.Text("Datos del producto",
                                    weight=ft.FontWeight.BOLD, size=16),
                            titulo,
                            descripcion,
                        ],
                        col={"sm": 12, "md": 7},
                        spacing=10,
                    ),
                    ft.Column(
                        controls=[
                            ft.Text("Detalles",
                                    weight=ft.FontWeight.BOLD, size=16),
                            categoria,
                            genero,
                            color,
                            talles,
                            palabras_clave,
                            url_slug,
                            precio,
                            ft.Container(height=10),
                            ft.Row([
                                ft.ElevatedButton(
                                    "Guardar cambios",
                                    icon=ft.Icons.SAVE,
                                    on_click=_guardar,
                                    style=ft.ButtonStyle(
                                        padding=ft.padding.all(16),
                                    ),
                                ),
                                ft.OutlinedButton(
                                    "Volver",
                                    on_click=lambda _: page.go("/grid"),
                                ),
                            ]),
                        ],
                        col={"sm": 12, "md": 5},
                        spacing=10,
                    ),
                ]),
                padding=ft.padding.all(20),
                expand=True,
            ),
        ],
    )
    return view
