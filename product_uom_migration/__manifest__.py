{
    "name": "Product UoM Migration",
    "version": "19.0.1.0.0",
    "summary": "Migrate a product to a new Unit of Measure by creating a "
                "replacement product and transferring stock.",
    "category": "Inventory",
    "author": "Vidyasree",
    "depends": ["stock", "sale", "purchase"],
    "data": [
        "security/ir.model.access.csv",
        "views"
        "/product_uom_migration_wizard_views.xml",
        "views/product_views.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}