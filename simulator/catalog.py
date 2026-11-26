"""Listas fixas usadas na geração dos dados sintéticos (municípios com código IBGE)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Ingredient:
    name: str
    category: str
    dosages: tuple[str, ...]
    forms: tuple[str, ...]
    requires_prescription: bool
    base_price_cents: int  # preço de referência para uma caixa com 10 unidades


@dataclass(frozen=True, slots=True)
class City:
    ibge_code: int
    name: str
    state: str
    area_code: int


MEDICINES: tuple[Ingredient, ...] = (
    Ingredient(
        "Paracetamol", "ANALGESICO", ("500mg", "750mg"), ("comprimido", "gotas"), False, 450
    ),
    Ingredient(
        "Dipirona sódica", "ANALGESICO", ("500mg", "1g"), ("comprimido", "gotas"), False, 520
    ),
    Ingredient("Ibuprofeno", "ANTI_INFLAMATORIO", ("400mg", "600mg"), ("comprimido",), False, 780),
    Ingredient("Nimesulida", "ANTI_INFLAMATORIO", ("100mg",), ("comprimido", "gotas"), True, 690),
    Ingredient(
        "Amoxicilina", "ANTIBIOTICO", ("500mg", "875mg"), ("cápsula", "suspensão oral"), True, 1890
    ),
    Ingredient(
        "Azitromicina", "ANTIBIOTICO", ("500mg",), ("comprimido", "suspensão oral"), True, 2450
    ),
    Ingredient("Cefalexina", "ANTIBIOTICO", ("500mg",), ("cápsula", "suspensão oral"), True, 2120),
    Ingredient(
        "Losartana potássica", "ANTI_HIPERTENSIVO", ("50mg", "100mg"), ("comprimido",), True, 980
    ),
    Ingredient("Enalapril", "ANTI_HIPERTENSIVO", ("10mg", "20mg"), ("comprimido",), True, 760),
    Ingredient("Atenolol", "ANTI_HIPERTENSIVO", ("25mg", "50mg"), ("comprimido",), True, 640),
    Ingredient("Anlodipino", "ANTI_HIPERTENSIVO", ("5mg", "10mg"), ("comprimido",), True, 870),
    Ingredient("Hidroclorotiazida", "DIURETICO", ("25mg",), ("comprimido",), True, 430),
    Ingredient("Metformina", "ANTIDIABETICO", ("500mg", "850mg"), ("comprimido",), True, 690),
    Ingredient("Glibenclamida", "ANTIDIABETICO", ("5mg",), ("comprimido",), True, 410),
    Ingredient("Sinvastatina", "HIPOLIPEMIANTE", ("20mg", "40mg"), ("comprimido",), True, 1150),
    Ingredient("Atorvastatina", "HIPOLIPEMIANTE", ("20mg", "40mg"), ("comprimido",), True, 2380),
    Ingredient("Omeprazol", "ANTIULCEROSO", ("20mg", "40mg"), ("cápsula",), False, 1240),
    Ingredient("Pantoprazol", "ANTIULCEROSO", ("20mg", "40mg"), ("comprimido",), True, 1980),
    Ingredient("Loratadina", "ANTIALERGICO", ("10mg",), ("comprimido", "xarope"), False, 890),
    Ingredient("Dexclorfeniramina", "ANTIALERGICO", ("2mg",), ("comprimido", "xarope"), False, 720),
    Ingredient("Prednisona", "CORTICOIDE", ("5mg", "20mg"), ("comprimido",), True, 610),
    Ingredient(
        "Dexametasona", "CORTICOIDE", ("4mg",), ("comprimido", "solução injetável"), True, 830
    ),
    Ingredient("Salbutamol", "BRONCODILATADOR", ("100mcg",), ("aerossol", "xarope"), True, 1760),
    Ingredient(
        "Levotiroxina", "HORMONIO", ("25mcg", "50mcg", "100mcg"), ("comprimido",), True, 1320
    ),
    Ingredient("Sertralina", "ANTIDEPRESSIVO", ("50mg", "100mg"), ("comprimido",), True, 2890),
    Ingredient("Fluoxetina", "ANTIDEPRESSIVO", ("20mg",), ("cápsula", "gotas"), True, 1540),
    Ingredient("Clonazepam", "ANSIOLITICO", ("0,5mg", "2mg"), ("comprimido", "gotas"), True, 1080),
    Ingredient(
        "Insulina humana NPH", "ANTIDIABETICO", ("100UI/ml",), ("frasco-ampola",), True, 4590
    ),
    Ingredient(
        "Heparina sódica", "ANTICOAGULANTE", ("5.000UI/ml",), ("solução injetável",), True, 3870
    ),
    Ingredient(
        "Cloreto de sódio",
        "SOLUCAO_PARENTERAL",
        ("0,9%",),
        ("bolsa 500ml", "bolsa 250ml"),
        True,
        690,
    ),
    Ingredient("Vitamina C", "SUPLEMENTO", ("1g",), ("comprimido efervescente",), False, 1190),
    Ingredient(
        "Vitamina D3", "SUPLEMENTO", ("1.000UI", "2.000UI"), ("cápsula", "gotas"), False, 1650
    ),
    Ingredient("Sulfato ferroso", "SUPLEMENTO", ("40mg",), ("comprimido", "gotas"), False, 520),
)

# Materiais hospitalares e itens de higiene não têm dosagem: a "forma" descreve o item.
SUPPLIES: tuple[Ingredient, ...] = (
    Ingredient(
        "Seringa descartável", "MATERIAL_HOSPITALAR", ("5ml", "10ml"), ("sem agulha",), False, 650
    ),
    Ingredient(
        "Agulha hipodérmica", "MATERIAL_HOSPITALAR", ("25x7", "40x12"), ("estéril",), False, 380
    ),
    Ingredient(
        "Luva de procedimento", "MATERIAL_HOSPITALAR", ("P", "M", "G"), ("látex",), False, 290
    ),
    Ingredient(
        "Máscara cirúrgica", "MATERIAL_HOSPITALAR", ("tripla",), ("com elástico",), False, 210
    ),
    Ingredient("Gaze", "MATERIAL_HOSPITALAR", ("7,5x7,5cm",), ("estéril",), False, 340),
    Ingredient(
        "Cateter intravenoso", "MATERIAL_HOSPITALAR", ("20G", "22G"), ("periférico",), False, 1890
    ),
    Ingredient(
        "Equipo", "MATERIAL_HOSPITALAR", ("macrogotas",), ("com injetor lateral",), False, 960
    ),
    Ingredient("Álcool etílico", "HIGIENE", ("70%",), ("frasco 1L", "gel 500ml"), False, 1490),
    Ingredient(
        "Sabonete antisséptico", "HIGIENE", ("clorexidina 2%",), ("frasco 1L",), False, 2190
    ),
)

MEDICINE_PACK_SIZES: tuple[int, ...] = (10, 20, 30, 60)
SUPPLY_PACK_SIZES: tuple[int, ...] = (1, 10, 50, 100)

# Fabricantes fictícios, com um fator de preço (marca mais cara ou mais barata).
MANUFACTURERS: tuple[tuple[str, float], ...] = (
    ("Aurora Farma", 1.00),
    ("Vale Verde Farmacêutica", 0.85),
    ("Biosul Lab", 0.92),
    ("Medicor Exemplo", 1.25),
    ("Vitalis Pharma", 1.10),
    ("Cruzeiro Hospitalar", 0.95),
    ("Alfa Insumos", 0.80),
)

CITIES: tuple[City, ...] = (
    City(3550308, "São Paulo", "SP", 11),
    City(3509502, "Campinas", "SP", 19),
    City(3543402, "Ribeirão Preto", "SP", 16),
    City(3304557, "Rio de Janeiro", "RJ", 21),
    City(3106200, "Belo Horizonte", "MG", 31),
    City(3170206, "Uberlândia", "MG", 34),
    City(3205309, "Vitória", "ES", 27),
    City(4106902, "Curitiba", "PR", 41),
    City(4113700, "Londrina", "PR", 43),
    City(4205407, "Florianópolis", "SC", 48),
    City(4314902, "Porto Alegre", "RS", 51),
    City(2927408, "Salvador", "BA", 71),
    City(2611606, "Recife", "PE", 81),
    City(2304400, "Fortaleza", "CE", 85),
    City(2408102, "Natal", "RN", 84),
    City(2507507, "João Pessoa", "PB", 83),
    City(5300108, "Brasília", "DF", 61),
    City(5208707, "Goiânia", "GO", 62),
    City(1302603, "Manaus", "AM", 92),
    City(1501402, "Belém", "PA", 91),
)

# Peso de cada cidade na base de clientes (capitais grandes concentram mais clientes).
CITY_WEIGHTS: tuple[float, ...] = (
    18,
    5,
    3,
    10,
    8,
    2,
    2,
    6,
    2,
    2,
    5,
    5,
    4,
    4,
    1,
    1,
    4,
    3,
    2,
    2,
)

# Centros de distribuição, na ordem em que são criados (o perfil define quantos existem).
WAREHOUSES: tuple[tuple[str, int], ...] = (
    ("CD Campinas", 3509502),
    ("CD Curitiba", 4106902),
    ("CD Recife", 2611606),
    ("CD Goiânia", 5208707),
    ("CD Belém", 1501402),
)

# Qual CD atende cada estado (índice em WAREHOUSES). Se o CD não existir no perfil, usa o 0.
STATE_TO_WAREHOUSE: dict[str, int] = {
    "SP": 0,
    "RJ": 0,
    "MG": 0,
    "ES": 0,
    "PR": 1,
    "SC": 1,
    "RS": 1,
    "BA": 2,
    "PE": 2,
    "CE": 2,
    "RN": 2,
    "PB": 2,
    "DF": 3,
    "GO": 3,
    "AM": 4,
    "PA": 4,
}

PHARMACY_PREFIXES: tuple[str, ...] = ("Farmácia", "Drogaria", "Drogaria e Perfumaria")
CLINIC_PREFIXES: tuple[str, ...] = ("Clínica", "Policlínica", "Centro Médico")
HOSPITAL_PREFIXES: tuple[str, ...] = ("Hospital", "Hospital e Maternidade")
NAME_PARTS: tuple[str, ...] = (
    "Santa Luzia",
    "São Bento",
    "Vida",
    "Bem Estar",
    "Popular",
    "Central",
    "Esperança",
    "Nova Era",
    "Saúde Total",
    "Boa Vista",
    "Primavera",
    "Santa Clara",
    "Do Povo",
    "Vale do Sol",
    "Horizonte",
    "Bom Pastor",
    "Jardim",
    "Aliança",
    "Estrela",
    "Familiar",
    "Avenida",
    "Cristal",
    "Bela Vista",
    "Santo Antônio",
    "Imperial",
    "Nossa Senhora",
)
FIRST_NAMES: tuple[str, ...] = (
    "Ana",
    "Bruno",
    "Carla",
    "Diego",
    "Elisa",
    "Fábio",
    "Gabriela",
    "Heitor",
    "Isabela",
    "João",
    "Larissa",
    "Marcos",
    "Natália",
    "Otávio",
    "Paula",
    "Rafael",
    "Sofia",
    "Thiago",
)
LAST_NAMES: tuple[str, ...] = (
    "Almeida",
    "Barbosa",
    "Cardoso",
    "Dias",
    "Esteves",
    "Ferreira",
    "Gomes",
    "Lima",
    "Moreira",
    "Nunes",
    "Oliveira",
    "Pereira",
    "Ribeiro",
    "Souza",
    "Teixeira",
    "Vieira",
)
