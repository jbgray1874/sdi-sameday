"""Andy Baxter briefing field schema, retained from the original application."""
FIELDS = {
    # Section 1 - Headline information
    "project_name":         ("Project name", "1. Headline information", False),
    "account_manager":      ("Project account manager", "1. Headline information", False),
    "client":               ("Brand or retail client", "1. Headline information", True),
    "customer_name":        ("Customer's name (contact)", "1. Headline information", False),
    "instore_date":         ("Anticipated completion date in store", "1. Headline information", False),
    # Section 3 - Main briefing (the visual needs these first)
    "unit_type":            ("What the unit is", "3. Main briefing", True),
    "narrative":            ("Customer requirement - role of the unit, what they hope to achieve", "3. Main briefing", False),
    "materials":            ("Materials / finish", "3. Main briefing", True),
    "size":                 ("Approx. height x width x depth", "3. Main briefing", True),
    "placement":            ("Where it will be deployed in store", "3. Main briefing", True),
    "colours_graphics":     ("Colours and brand graphics", "3. Main briefing", False),
    "products_held":        ("Products it displays", "3. Main briefing", False),
    "shelf_life":           ("Anticipated life in store", "3. Main briefing", False),
    "references":           ("Design / artwork reference supplied by the client", "3. Main briefing", False),
    "warehousing":          ("SDI warehousing, or direct to store", "3. Main briefing", False),
    "assembled":            ("Supplied fully assembled or flat-packed", "3. Main briefing", False),
    "output":               ("Quick response wanted: 3D render, technical GA or both", "5. Quick design & technical response", False),
    # Section 2 - Project information
    "creative_required":    ("Creative design output required", "2. Project information", False),
    "creative_chargeable":  ("Creative chargeable? Budget (GBP)", "2. Project information", False),
    "creative_due":         ("Creative response due", "2. Project information", False),
    "technical_required":   ("Technical design required", "2. Project information", False),
    "technical_chargeable": ("Technical chargeable? Budget (GBP)", "2. Project information", False),
    "technical_due":        ("Technical response due", "2. Project information", False),
    "prototype_required":   ("Prototype required", "2. Project information", False),
    "prototype_chargeable": ("Prototype chargeable? Budget (GBP)", "2. Project information", False),
    "prototype_due":        ("Prototype complete by", "2. Project information", False),
    "volume_required":      ("Volume manufacture required", "2. Project information", False),
    "volume_qty":           ("Anticipated volume (units)", "2. Project information", False),
    "leadtime":             ("Preferred manufacturing lead time", "2. Project information", False),
    "installation":         ("Installation by SDI", "2. Project information", False),
    "repeat":               ("Likely to repeat, and how often", "2. Project information", False),
    "similar_projects":     ("Similar past projects to reference", "2. Project information", False),
    # Section 4 - Estimating information
    "estimate_required":    ("Project estimate required", "4. Estimating information", False),
    "region":               ("Quote from UK, Europe or China", "4. Estimating information", False),
    "production_drawings":  ("Production-ready drawings available", "4. Estimating information", False),
    "prototype_cost":       ("Prototype cost required", "4. Estimating information", False),
    "production_cost":      ("Production cost required", "4. Estimating information", False),
    "target_unit_cost":     ("Client target budget per unit", "4. Estimating information", False),
    "finish_instructions":  ("Special raw material or paint finish instructions", "4. Estimating information", False),
    "delivery_packing":     ("Bulk supplied or palletised", "4. Estimating information", False),
    "delivery_restrictions":("Delivery instructions / warehouse restrictions", "4. Estimating information", False),
    "estimate_due":         ("Estimate required by", "4. Estimating information", False),
}
NEED = [k for k, v in FIELDS.items() if v[2]]
SECTIONS = ["1. Headline information", "2. Project information", "3. Main briefing", "4. Estimating information",
            "5. Quick design & technical response"]
RATE_GBP = 75   # Andy: hours allocated from budget at GBP75/hour, rounded up
