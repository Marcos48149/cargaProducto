class ProductGroup:
    def __init__(self, sku, images):
        self.sku = sku
        self.images = images
        self.titulo = None
        self.descripcion = None
        self.color = None
        self.categoria = None
        self.genero = None
        self.talles = None
        self.palabras_clave = None
        self.url_slug = None
        self.precio = 0
        self.precio_tachado = None
        self.estado = "Pendiente"
        self.web_title = None

    @property
    def preview_titulo(self):
        return self.titulo or f"{self.sku} — pendiente"


class AppState:
    def __init__(self):
        self.products = []
        self.folder_path = None

    def add_product(self, sku, images):
        self.products.append(ProductGroup(sku, images))

    def get_product(self, sku):
        for p in self.products:
            if p.sku == sku:
                return p
        return None
