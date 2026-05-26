import argparse
import csv
import math
import os
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass

try:
    import pulp
except ImportError:
    pulp = None


# HEPSIJET ANAHAT OPTIMIZASYON ALGORITMASI
#
# Bu dosyanin amaci:
# - Gunluk cikis-varis desi taleplerini okumak
# - Kiralik araclari once kullanmak
# - Kalan yuk icin en ucuz spot arac kombinasyonunu bulmak
# - Uygunsa yukleri ara transfer merkezleri uzerinden konsolide etmek
# - Sonucta tum yukleri tasiyan en dusuk maliyetli gunluk plan uretmek
#
# Not:
# PuLP kuruluysa model MILP olarak global optimum arar.
# PuLP yoksa saf Python greedy/yaklasik mod calisir.
# Excel dosyalari zip/xml olarak okunuyor ve mesafe koordinatlardan tahmin ediliyor.
WORKSPACE = os.path.dirname(os.path.abspath(__file__))


def clean_text(value):
    # Excel'den gelen metinleri standart unicode forma getirir.
    # Bu, "İstanbul" gibi Turkce karakterli merkez adlarinin karsilastirilmasini kolaylastirir.
    if value is None:
        return ""
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value).strip()
    return value


def to_float(value, default=0.0):
    # Excel hucreleri bazen metin olarak gelir. Maliyet/desi/mesafe alanlarini sayiya cevirir.
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def to_int(value, default=0):
    # Arac sayisi gibi tam sayi beklenen alanlar icin yardimci donusum.
    return int(round(to_float(value, default)))


def excel_serial_to_iso(serial):
    # Excel's 1900 date system. 25569 is 1970-01-01.
    try:
        serial = int(float(serial))
    except (TypeError, ValueError):
        return str(serial)
    from datetime import date, timedelta

    return (date(1970, 1, 1) + timedelta(days=serial - 25569)).isoformat()


def read_xlsx(path):
    # Excel dosyalari aslinda ZIP icinde XML dosyalarindan olusur.
    # Harici kutuphane kurmadan calissin diye xlsx okumasini burada kendimiz yapiyoruz.
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        shared_strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall(".//m:si", ns):
                texts = [node.text or "" for node in item.findall(".//m:t", ns)]
                shared_strings.append(clean_text("".join(texts)))

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheet_names = [
            clean_text(sheet.attrib.get("name"))
            for sheet in workbook.findall(".//m:sheet", ns)
        ]

        sheets = {}
        for index, sheet_name in enumerate(sheet_names, start=1):
            sheet_path = f"xl/worksheets/sheet{index}.xml"
            if sheet_path not in archive.namelist():
                continue

            sheet = ET.fromstring(archive.read(sheet_path))
            rows_by_index = {}
            max_col = 0
            for row in sheet.findall(".//m:sheetData/m:row", ns):
                row_index = int(row.attrib["r"])
                values = {}
                for cell in row.findall("m:c", ns):
                    ref = cell.attrib.get("r", "")
                    col_letters = "".join(ch for ch in ref if ch.isalpha())
                    col_index = 0
                    for ch in col_letters:
                        col_index = col_index * 26 + (ord(ch.upper()) - 64)
                    max_col = max(max_col, col_index)

                    value_node = cell.find("m:v", ns)
                    value = None
                    if value_node is not None and value_node.text is not None:
                        value = value_node.text
                        if cell.attrib.get("t") == "s":
                            value = shared_strings[int(value)]
                        elif cell.attrib.get("t") == "b":
                            value = value == "1"
                    values[col_index] = clean_text(value)
                rows_by_index[row_index] = values

            if not rows_by_index:
                sheets[sheet_name] = []
                continue

            max_row = max(rows_by_index)
            matrix = []
            for row_index in range(1, max_row + 1):
                row = rows_by_index.get(row_index, {})
                matrix.append([row.get(col_index) for col_index in range(1, max_col + 1)])
            sheets[sheet_name] = matrix
    return sheets


def table_from_first_sheet(path):
    # Bir Excel dosyasinin ilk sayfasini baslik -> deger sozlukleri listesine cevirir.
    # Ornek sonuc: [{"Araç Adı": "Tır", "Kapasite (desi)": 22400, ...}, ...]
    sheets = read_xlsx(path)
    rows = next(iter(sheets.values()))
    headers = [clean_text(header) for header in rows[0]]
    records = []
    for row in rows[1:]:
        if not any(cell not in (None, "") for cell in row):
            continue
        records.append({headers[i]: clean_text(row[i]) if i < len(row) else "" for i in range(len(headers))})
    return records


@dataclass(frozen=True)
class VehicleType:
    # Arac tipinin kapasite ve maliyet parametrelerini tutar.
    # Kiralik ve spot araclarin maliyet yapilari farkli oldugu icin ikisi de saklanir.
    name: str
    capacity: float
    rental_daily_cost: float
    rental_km_cost: float
    spot_daily_cost: float
    spot_km_cost: float


@dataclass
class Assignment:
    # Nihai arac planindaki tek satiri temsil eder.
    # Bir satir, belirli bir fiziksel hatta kac arac calisacagini ve kac desi tasiyacagini anlatir.
    date: str
    shipment_origin: str
    shipment_destination: str
    transfer_center: str
    leg_no: int
    origin: str
    destination: str
    vehicle_type: str
    source: str
    vehicle_count: int
    loaded_desi: float
    capacity_desi: float
    distance_km: float
    cost_tl: float

    @property
    def utilization(self):
        if self.capacity_desi <= 0:
            return 0.0
        return self.loaded_desi / self.capacity_desi


@dataclass
class FlowDecision:
    # Bir talebin hangi yoldan gidecegini temsil eder.
    # path dogrudan olabilir: ("Kocaeli", "Yalova")
    # path aktarmali olabilir: ("Kocaeli", "Manisa", "Yalova")
    date: str
    origin: str
    destination: str
    demand_desi: float
    path: tuple
    estimated_cost_tl: float

    @property
    def transfer_center(self):
        return self.path[1] if len(self.path) == 3 else ""


@dataclass
class OptimizationResult:
    # optimize fonksiyonunun tek parca sonuc nesnesi.
    # solver_status alani planin greedy mi MILP mi uretildigini anlatir.
    assignments: list
    unmet_routes: list
    flow_decisions: list
    solver_status: str


def load_vehicle_types(path):
    # Arac kapasite/maliyet dosyasindan turlari okur.
    # Buyuk kapasiteli araclar once gelsin diye kapasiteye gore azalan siralanir.
    records = table_from_first_sheet(path)
    vehicles = []
    for record in records:
        vehicles.append(
            VehicleType(
                name=clean_text(record["Araç Adı"]),
                capacity=to_float(record["Kapasite (desi)"]),
                rental_daily_cost=to_float(record["Kiralık Araç Günlük Kira (TL)"]),
                rental_km_cost=to_float(record["Kiralık Araç Kilometre Başına Maliyet (TL)"]),
                spot_daily_cost=to_float(record["Spot Araç Sabit Günlük Maliyet (TL)"]),
                spot_km_cost=to_float(record["Spot Kilometre Başına Maliyet (TL)"]),
            )
        )
    return sorted(vehicles, key=lambda vehicle: vehicle.capacity, reverse=True)


def load_coordinates(path):
    # Transfer merkezlerinin koordinatlarini okur.
    # Bu koordinatlar mesafe tahmini icin kullanilir.
    records = table_from_first_sheet(path)
    coordinates = {}
    for record in records:
        coordinates[clean_text(record["Transfer Merkezi"])] = (
            to_float(record["Enlem"]),
            to_float(record["Boylam"]),
        )
    return coordinates


def load_rental_inventory(path):
    # Kiralik arac envanterini okur.
    # Cikis-varis hattina gore hangi arac tipinden kac tane oldugunu saklar.
    records = table_from_first_sheet(path)
    inventory = defaultdict(lambda: defaultdict(int))
    for record in records:
        key = (
            clean_text(record["Çıkış Transfer Merkezi"]),
            clean_text(record["Varış Transfer Merkezi"]),
        )
        inventory[key][clean_text(record["Araç Türü"])] += to_int(record["Araç sayısı"])
    return inventory


def load_demands(path, selected_date=None):
    # Talep dosyasini gun + cikis + varis bazinda topluyoruz.
    # Tarih verilmezse model veri setindeki en guncel gunu planlar.
    records = table_from_first_sheet(path)
    demand_by_date_route = defaultdict(float)
    for record in records:
        date_value = excel_serial_to_iso(record["Tarih"])
        if selected_date and selected_date != date_value:
            continue
        key = (
            date_value,
            clean_text(record["Çıkış Transfer Merkezi"]),
            clean_text(record["Varış Transfer Merkezi"]),
        )
        demand_by_date_route[key] += to_float(record["Toplam Desi"])

    if selected_date:
        return demand_by_date_route

    latest_date = max((date for date, _, _ in demand_by_date_route), default=None)
    if latest_date is None:
        return {}
    return {
        key: value
        for key, value in demand_by_date_route.items()
        if key[0] == latest_date
    }


def haversine_km(point_a, point_b):
    # Iki koordinat arasindaki kus ucusu mesafeyi hesaplar.
    # Sonra route_distance fonksiyonunda karayolu yaklasimi icin katsayi uygulanir.
    lat1, lon1 = point_a
    lat2, lon2 = point_b
    radius = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def route_distance(origin, destination, coordinates, road_factor):
    # Elimizde karayolu mesafe matrisi olmadigi icin MVP'de koordinatlardan
    # kus ucusu mesafeyi hesaplayip karayolu yaklasim katsayisi ile carpariz.
    if origin not in coordinates or destination not in coordinates:
        return 0.0
    return haversine_km(coordinates[origin], coordinates[destination]) * road_factor


def vehicle_trip_cost(vehicle, source, distance_km):
    # Tek bir aracin tek bir hatta calismasinin maliyetini hesaplar.
    # Kiralik arac: gunluk kira + km maliyeti
    # Spot arac: spot sabit maliyet + spot km maliyeti
    if source == "kiralik":
        return vehicle.rental_daily_cost + vehicle.rental_km_cost * distance_km
    return vehicle.spot_daily_cost + vehicle.spot_km_cost * distance_km


def copy_inventory(inventory):
    # Kiralik arac envanterini kopyalar.
    # Aktarma denemelerinde orijinal envanteri bozmadan senaryo maliyeti hesaplamak icin kullanilir.
    copied = defaultdict(lambda: defaultdict(int))
    for route, vehicles in inventory.items():
        for vehicle_name, count in vehicles.items():
            copied[route][vehicle_name] = count
    return copied


def choose_spot_combo(remaining_desi, vehicles, distance_km):
    # Kiralik araclar yetmediginde kalan desiyi spot araclarla kapatiyoruz.
    # Burada kucuk bir tam sayili arama var: tum arac kombinasyonlarini deneyip
    # kapasiteyi asmayacak sekilde en dusuk maliyetli kombinasyonu seciyor.
    if remaining_desi <= 0:
        return []

    min_capacity = min(vehicle.capacity for vehicle in vehicles)
    max_total_count = int(math.ceil(remaining_desi / min_capacity)) + 3
    best = None

    def search(index, counts, capacity, cost):
        # Recursive arama:
        # Her arac tipi icin 0, 1, 2, ... adet kullanma ihtimallerini dener.
        # En ucuz ve kapasiteyi karsilayan kombinasyon best icinde tutulur.
        nonlocal best
        if best is not None and cost > best["cost"]:
            return
        if index == len(vehicles):
            if capacity >= remaining_desi:
                excess = capacity - remaining_desi
                total_count = sum(counts)
                candidate = {
                    "counts": tuple(counts),
                    "capacity": capacity,
                    "cost": cost,
                    "excess": excess,
                    "total_count": total_count,
                }
                if best is None:
                    best = candidate
                else:
                    key = (candidate["cost"], candidate["excess"], candidate["total_count"])
                    best_key = (best["cost"], best["excess"], best["total_count"])
                    if key < best_key:
                        best = candidate
            return

        vehicle = vehicles[index]
        if sum(counts) >= max_total_count:
            return

        max_count = max_total_count - sum(counts)
        if index == len(vehicles) - 1:
            needed = max(0, math.ceil((remaining_desi - capacity) / vehicle.capacity))
            count_options = [needed] if needed <= max_count else []
        else:
            count_options = range(max_count + 1)

        unit_cost = vehicle_trip_cost(vehicle, "spot", distance_km)
        for count in count_options:
            counts.append(count)
            search(
                index + 1,
                counts,
                capacity + count * vehicle.capacity,
                cost + count * unit_cost,
            )
            counts.pop()

    search(0, [], 0.0, 0.0)
    if best is None:
        return []
    return [
        (vehicles[index], count)
        for index, count in enumerate(best["counts"])
        if count > 0
    ]


def plan_leg(
    date_value,
    shipment_origin,
    shipment_destination,
    transfer_center,
    leg_no,
    leg_origin,
    leg_destination,
    demand,
    vehicle_types,
    vehicle_by_name,
    rentals,
    coordinates,
    road_factor,
    mutate_inventory=True,
):
    # Bir "bacak" fiziksel tasima hattidir: Kocaeli -> Manisa gibi.
    # Once bu hatta tanimli kiralik araclari kullanir, kalan yuk varsa spot arac ekler.
    # mutate_inventory=True iken kullanilan kiralik arac envanterden dusulur;
    # boylece ayni arac gun icinde iki farkli hatta tekrar kullanilmaz.
    remaining = demand
    distance_km = route_distance(leg_origin, leg_destination, coordinates, road_factor)
    assignments = []

    # 1) Once bu fiziksel hatta var olan kiralik araclari kullan.
    # Kiralik araclar sozlesmeli oldugu icin spot araca gecmeden once bunlar degerlendirilir.
    for vehicle_name, count in sorted(
        rentals[(leg_origin, leg_destination)].items(),
        key=lambda item: vehicle_by_name[item[0]].capacity,
        reverse=True,
    ):
        if remaining <= 0:
            break
        if count <= 0:
            continue
        vehicle = vehicle_by_name[vehicle_name]
        used_count = min(count, math.ceil(remaining / vehicle.capacity))
        loaded = min(remaining, used_count * vehicle.capacity)
        capacity = used_count * vehicle.capacity
        cost = used_count * vehicle_trip_cost(vehicle, "kiralik", distance_km)
        assignments.append(
            Assignment(
                date=date_value,
                shipment_origin=shipment_origin,
                shipment_destination=shipment_destination,
                transfer_center=transfer_center,
                leg_no=leg_no,
                origin=leg_origin,
                destination=leg_destination,
                vehicle_type=vehicle.name,
                source="kiralik",
                vehicle_count=used_count,
                loaded_desi=loaded,
                capacity_desi=capacity,
                distance_km=distance_km,
                cost_tl=cost,
            )
        )
        remaining -= loaded
        if mutate_inventory:
            rentals[(leg_origin, leg_destination)][vehicle_name] -= used_count

    # 2) Kiralik arac kapasitesi yetmediyse kalan yuk spot araclarla tamamlanir.
    # choose_spot_combo kalan desiyi karsilayan en dusuk maliyetli kombinasyonu getirir.
    for vehicle, count in choose_spot_combo(remaining, vehicle_types, distance_km):
        loaded = min(remaining, count * vehicle.capacity)
        capacity = count * vehicle.capacity
        cost = count * vehicle_trip_cost(vehicle, "spot", distance_km)
        assignments.append(
            Assignment(
                date=date_value,
                shipment_origin=shipment_origin,
                shipment_destination=shipment_destination,
                transfer_center=transfer_center,
                leg_no=leg_no,
                origin=leg_origin,
                destination=leg_destination,
                vehicle_type=vehicle.name,
                source="spot",
                vehicle_count=count,
                loaded_desi=loaded,
                capacity_desi=capacity,
                distance_km=distance_km,
                cost_tl=cost,
            )
        )
        remaining -= loaded

    return assignments, max(0.0, remaining)


def estimate_path_cost(path, demand, vehicle_types, vehicle_by_name, rentals, coordinates, road_factor):
    # Bir yuk icin secilecek yolun tahmini maliyetini hesaplar.
    # Yol dogrudan olabilir: A -> B
    # Ya da tek aktarmali olabilir: A -> C -> B
    simulated_rentals = copy_inventory(rentals)
    total_cost = 0.0
    for leg_no, (leg_origin, leg_destination) in enumerate(zip(path, path[1:]), start=1):
        assignments, remaining = plan_leg(
            date_value="estimate",
            shipment_origin=path[0],
            shipment_destination=path[-1],
            transfer_center=path[1] if len(path) == 3 else "",
            leg_no=leg_no,
            leg_origin=leg_origin,
            leg_destination=leg_destination,
            demand=demand,
            vehicle_types=vehicle_types,
            vehicle_by_name=vehicle_by_name,
            rentals=simulated_rentals,
            coordinates=coordinates,
            road_factor=road_factor,
            mutate_inventory=True,
        )
        if remaining > 0.01:
            return math.inf
        total_cost += sum(item.cost_tl for item in assignments)
    return total_cost


def choose_flow_paths(demands, vehicle_types, vehicle_by_name, rentals, coordinates, road_factor, allow_consolidation):
    # Konsolidasyon karari burada verilir.
    # Baslangicta tum yukler dogrudan tasinir. Sonra her yuk icin tek tek
    # olasi aktarma merkezleri denenir. Eger toplam gunluk maliyeti dusuruyorsa
    # o yuk aktarmali yola alinir. Bu greedy iyilestirme maliyet azalmayana kadar surer.
    flow_decisions = [
        FlowDecision(
            date=date_value,
            origin=origin,
            destination=destination,
            demand_desi=demand,
            path=(origin, destination),
            estimated_cost_tl=0.0,
        )
        for (date_value, origin, destination), demand in sorted(
            demands.items(),
            key=lambda item: item[1],
            reverse=True,
        )
    ]

    if not allow_consolidation:
        return flow_decisions

    transfer_centers = sorted(coordinates)

    # Baslangic maliyeti: hic aktarma yok, tum yukler dogrudan gidiyor.
    current_cost = total_cost_for_flows(
        flow_decisions,
        vehicle_types,
        vehicle_by_name,
        rentals,
        coordinates,
        road_factor,
    )

    improved = True
    while improved:
        improved = False

        # Her turda her talep icin tum aktarma merkezleri denenir.
        # En iyi degisiklik uygulanir; maliyet artik dusmuyorsa dongu biter.
        for index, flow in enumerate(flow_decisions):
            candidate_paths = [(flow.origin, flow.destination)]
            for center in transfer_centers:
                if center not in (flow.origin, flow.destination):
                    candidate_paths.append((flow.origin, center, flow.destination))

            best_flow = flow
            best_cost = current_cost
            for path in candidate_paths:
                if path == flow.path or any(path_part not in coordinates for path_part in path):
                    continue

                # Bu talebi gecici olarak yeni yola al,
                # sonra tum gunluk planin toplam maliyetine bak.
                candidate_flow = FlowDecision(
                    date=flow.date,
                    origin=flow.origin,
                    destination=flow.destination,
                    demand_desi=flow.demand_desi,
                    path=path,
                    estimated_cost_tl=0.0,
                )
                candidate_flows = list(flow_decisions)
                candidate_flows[index] = candidate_flow
                candidate_cost = total_cost_for_flows(
                    candidate_flows,
                    vehicle_types,
                    vehicle_by_name,
                    rentals,
                    coordinates,
                    road_factor,
                )
                if candidate_cost + 0.01 < best_cost:
                    best_cost = candidate_cost
                    best_flow = candidate_flow

            if best_flow.path != flow.path:
                # Aktarma toplam maliyeti gercekten dusurduyse kalici olarak kabul edilir.
                flow_decisions[index] = best_flow
                current_cost = best_cost
                improved = True

    return flow_decisions


def build_candidate_paths(origin, destination, coordinates, allow_consolidation):
    # Bir OD talebi icin izin verilen yollari uretir.
    # Ellecleme maliyeti istenmedigi icin aktarmali yolun ekstra sabit cezasi yoktur.
    paths = [(origin, destination)]
    if allow_consolidation:
        for center in sorted(coordinates):
            if center not in (origin, destination):
                paths.append((origin, center, destination))
    return [path for path in paths if all(node in coordinates for node in path)]


def solve_global_milp(demands, vehicle_types, vehicle_by_name, base_rentals, coordinates, road_factor, allow_consolidation):
    # Global optimum modeli:
    # x[i,p] = i talebi p yolunu secsin mi? (binary)
    # y[leg, arac, kaynak] = ilgili fiziksel hatta kac arac kullanilsin? (integer)
    #
    # Kisitlar:
    # - Her talep tam olarak bir yol secer.
    # - Her fiziksel hattaki toplam desi, o hatta acilan arac kapasitesini asamaz.
    # - Kiralik arac sayisi envanteri asamaz.
    #
    # Amac:
    # - Kiralik + spot arac maliyetlerinin toplamini minimize etmek.
    # - Ellecleme maliyeti bilincli olarak yoktur.
    if pulp is None:
        raise RuntimeError("PuLP kurulu degil; MILP/global optimum modu calisamaz.")

    demand_items = [
        {
            "key": key,
            "date": key[0],
            "origin": key[1],
            "destination": key[2],
            "demand": demand,
            "paths": build_candidate_paths(key[1], key[2], coordinates, allow_consolidation),
        }
        for key, demand in sorted(demands.items(), key=lambda item: item[1], reverse=True)
    ]

    problem = pulp.LpProblem("Hepsijet_Global_Linehaul_Optimization", pulp.LpMinimize)
    x_vars = {}
    legs = set()

    for i, item in enumerate(demand_items):
        for p_index, path in enumerate(item["paths"]):
            x_vars[(i, p_index)] = pulp.LpVariable(f"x_{i}_{p_index}", cat="Binary")
            for leg_origin, leg_destination in zip(path, path[1:]):
                legs.add((item["date"], leg_origin, leg_destination))

    y_vars = {}
    for date_value, leg_origin, leg_destination in sorted(legs):
        distance_km = route_distance(leg_origin, leg_destination, coordinates, road_factor)
        for vehicle in vehicle_types:
            rental_available = base_rentals[(leg_origin, leg_destination)].get(vehicle.name, 0)
            if rental_available > 0:
                var_key = (date_value, leg_origin, leg_destination, vehicle.name, "kiralik")
                y_vars[var_key] = pulp.LpVariable(
                    f"y_rental_{date_value}_{leg_origin}_{leg_destination}_{vehicle.name}",
                    lowBound=0,
                    upBound=rental_available,
                    cat="Integer",
                )

            var_key = (date_value, leg_origin, leg_destination, vehicle.name, "spot")
            y_vars[var_key] = pulp.LpVariable(
                f"y_spot_{date_value}_{leg_origin}_{leg_destination}_{vehicle.name}",
                lowBound=0,
                cat="Integer",
            )

    # Her talep bir ve yalniz bir yol secmeli.
    for i, item in enumerate(demand_items):
        problem += (
            pulp.lpSum(x_vars[(i, p_index)] for p_index in range(len(item["paths"]))) == 1,
            f"choose_one_path_{i}",
        )

    # Fiziksel hat kapasitesi: secilen yollarin o hatta bindirdigi toplam yuk <= acilan arac kapasitesi.
    for date_value, leg_origin, leg_destination in sorted(legs):
        load_terms = []
        for i, item in enumerate(demand_items):
            if item["date"] != date_value:
                continue
            for p_index, path in enumerate(item["paths"]):
                if (leg_origin, leg_destination) in set(zip(path, path[1:])):
                    load_terms.append(item["demand"] * x_vars[(i, p_index)])

        capacity_terms = []
        for vehicle in vehicle_types:
            for source in ("kiralik", "spot"):
                var = y_vars.get((date_value, leg_origin, leg_destination, vehicle.name, source))
                if var is not None:
                    capacity_terms.append(vehicle.capacity * var)

        problem += (
            pulp.lpSum(load_terms) <= pulp.lpSum(capacity_terms),
            f"capacity_{date_value}_{leg_origin}_{leg_destination}",
        )

    objective_terms = []
    for (date_value, leg_origin, leg_destination, vehicle_name, source), var in y_vars.items():
        vehicle = vehicle_by_name[vehicle_name]
        distance_km = route_distance(leg_origin, leg_destination, coordinates, road_factor)
        objective_terms.append(vehicle_trip_cost(vehicle, source, distance_km) * var)
    problem += pulp.lpSum(objective_terms)

    solver = pulp.PULP_CBC_CMD(msg=False)
    problem.solve(solver)
    status = pulp.LpStatus.get(problem.status, str(problem.status))
    if status != "Optimal":
        raise RuntimeError(f"MILP optimum bulunamadi. Cozucu durumu: {status}")

    flow_decisions = []
    for i, item in enumerate(demand_items):
        chosen_path = None
        for p_index, path in enumerate(item["paths"]):
            if pulp.value(x_vars[(i, p_index)]) >= 0.5:
                chosen_path = path
                break
        if chosen_path is None:
            raise RuntimeError(f"MILP sonucu okunamadi: talep {i} icin yol secilmedi.")
        flow_decisions.append(
            FlowDecision(
                date=item["date"],
                origin=item["origin"],
                destination=item["destination"],
                demand_desi=item["demand"],
                path=chosen_path,
                estimated_cost_tl=0.0,
            )
        )

    assignments, unmet_routes = build_assignments_from_milp_solution(
        flow_decisions,
        vehicle_by_name,
        y_vars,
        coordinates,
        road_factor,
    )
    return assignments, unmet_routes, flow_decisions, f"MILP global optimum ({status})"


def build_assignments_from_milp_solution(flow_decisions, vehicle_by_name, y_vars, coordinates, road_factor):
    # MILP cozumunde arac sayilari y degiskenlerinden gelir.
    # Bu fonksiyon CSV'ye yazilacak arac planini dogrudan cozum degiskenlerinden olusturur.
    leg_loads = defaultdict(float)
    leg_flows = defaultdict(list)
    for flow in flow_decisions:
        for leg_origin, leg_destination in zip(flow.path, flow.path[1:]):
            leg_key = (flow.date, leg_origin, leg_destination)
            leg_loads[leg_key] += flow.demand_desi
            leg_flows[leg_key].append(flow)

    assignments = []
    unmet_routes = []

    for (date_value, leg_origin, leg_destination), demand in sorted(leg_loads.items()):
        flows = leg_flows[(date_value, leg_origin, leg_destination)]
        origins = sorted({flow.origin for flow in flows})
        destinations = sorted({flow.destination for flow in flows})
        transfers = sorted({flow.transfer_center for flow in flows if flow.transfer_center})
        leg_numbers = []
        for flow in flows:
            for index, pair in enumerate(zip(flow.path, flow.path[1:]), start=1):
                if pair == (leg_origin, leg_destination):
                    leg_numbers.append(index)

        shipment_origin = origins[0] if len(origins) == 1 else "Karma"
        shipment_destination = destinations[0] if len(destinations) == 1 else "Karma"
        transfer_center = transfers[0] if len(transfers) == 1 else ("Karma" if transfers else "")
        leg_no = leg_numbers[0] if len(set(leg_numbers)) == 1 else 0
        distance_km = route_distance(leg_origin, leg_destination, coordinates, road_factor)
        remaining = demand

        selected_vehicle_rows = []
        for (var_date, var_origin, var_destination, vehicle_name, source), var in y_vars.items():
            if (var_date, var_origin, var_destination) != (date_value, leg_origin, leg_destination):
                continue
            count = int(round(pulp.value(var) or 0))
            if count > 0:
                vehicle = vehicle_by_name[vehicle_name]
                selected_vehicle_rows.append((source, vehicle, count))

        # Once kiralik sonra spot, ayni kaynakta buyuk kapasiteden kucuge siraliyoruz.
        selected_vehicle_rows.sort(
            key=lambda item: (0 if item[0] == "kiralik" else 1, -item[1].capacity)
        )

        for source, vehicle, count in selected_vehicle_rows:
            capacity = count * vehicle.capacity
            loaded = min(remaining, capacity)
            cost = count * vehicle_trip_cost(vehicle, source, distance_km)
            assignments.append(
                Assignment(
                    date=date_value,
                    shipment_origin=shipment_origin,
                    shipment_destination=shipment_destination,
                    transfer_center=transfer_center,
                    leg_no=leg_no,
                    origin=leg_origin,
                    destination=leg_destination,
                    vehicle_type=vehicle.name,
                    source=source,
                    vehicle_count=count,
                    loaded_desi=loaded,
                    capacity_desi=capacity,
                    distance_km=distance_km,
                    cost_tl=cost,
                )
            )
            remaining -= loaded

        if remaining > 0.01:
            unmet_routes.append((date_value, leg_origin, leg_destination, remaining))

    return assignments, unmet_routes


def build_assignments_for_flows(flow_decisions, vehicle_types, vehicle_by_name, base_rentals, coordinates, road_factor):
    # Secilen yuk akislarini fiziksel arac planina cevirir.
    # Ornegin birden fazla yuk Kocaeli -> Manisa bacagini kullaniyorsa,
    # bunlar tek hatta birlestirilir ve araclar toplam desiye gore planlanir.
    leg_loads = defaultdict(float)
    leg_flows = defaultdict(list)
    for flow in flow_decisions:
        # Secilen yoldaki her bacak icin toplam yuku fiziksel hatta ekliyoruz.
        # Boylece ayni bacagi kullanan farkli talepler konsolide edilmis oluyor.
        for leg_origin, leg_destination in zip(flow.path, flow.path[1:]):
            leg_key = (flow.date, leg_origin, leg_destination)
            leg_loads[leg_key] += flow.demand_desi
            leg_flows[leg_key].append(flow)

    rentals = copy_inventory(base_rentals)
    assignments = []
    unmet_routes = []

    for (date_value, leg_origin, leg_destination), demand in sorted(leg_loads.items()):
        # Ayni bacakta birden fazla orijinal talep olabilir.
        # CSV'de okunabilirlik icin tek kaynak/hedef varsa onu, birden fazlaysa "Karma" yaziyoruz.
        flows = leg_flows[(date_value, leg_origin, leg_destination)]
        origins = sorted({flow.origin for flow in flows})
        destinations = sorted({flow.destination for flow in flows})
        transfers = sorted({flow.transfer_center for flow in flows if flow.transfer_center})
        leg_numbers = []
        for flow in flows:
            for index, pair in enumerate(zip(flow.path, flow.path[1:]), start=1):
                if pair == (leg_origin, leg_destination):
                    leg_numbers.append(index)

        shipment_origin = origins[0] if len(origins) == 1 else "Karma"
        shipment_destination = destinations[0] if len(destinations) == 1 else "Karma"
        transfer_center = transfers[0] if len(transfers) == 1 else ("Karma" if transfers else "")
        leg_no = leg_numbers[0] if len(set(leg_numbers)) == 1 else 0

        leg_assignments, remaining = plan_leg(
            date_value=date_value,
            shipment_origin=shipment_origin,
            shipment_destination=shipment_destination,
            transfer_center=transfer_center,
            leg_no=leg_no,
            leg_origin=leg_origin,
            leg_destination=leg_destination,
            demand=demand,
            vehicle_types=vehicle_types,
            vehicle_by_name=vehicle_by_name,
            rentals=rentals,
            coordinates=coordinates,
            road_factor=road_factor,
            mutate_inventory=True,
        )
        assignments.extend(leg_assignments)
        if remaining > 0.01:
            unmet_routes.append((date_value, leg_origin, leg_destination, remaining))

    return assignments, unmet_routes


def total_cost_for_flows(flow_decisions, vehicle_types, vehicle_by_name, base_rentals, coordinates, road_factor):
    # Bir yuk akisi setinin toplam arac maliyetini hesaplar.
    # Konsolidasyon kararlarini karsilastirirken bu fonksiyon objektif fonksiyon gibi davranir.
    assignments, unmet_routes = build_assignments_for_flows(
        flow_decisions,
        vehicle_types,
        vehicle_by_name,
        base_rentals,
        coordinates,
        road_factor,
    )
    if unmet_routes:
        return math.inf
    return sum(item.cost_tl for item in assignments)


def optimize(selected_date=None, road_factor=1.25, allow_consolidation=True, method="auto"):
    # Ana is akisi:
    # 1. Excel verilerini oku.
    # 2. Yuklerin dogrudan/aktarmali yollarini sec.
    # 3. Secilen akislari arac planina donustur.
    # 4. CSV ciktilarini uretmek icin sonucu dondur.
    vehicle_types = load_vehicle_types(os.path.join(WORKSPACE, "Araç_Kapasite_Maliyet.xlsx"))
    coordinates = load_coordinates(os.path.join(WORKSPACE, "Koordinatlar.xlsx"))
    base_rentals = load_rental_inventory(os.path.join(WORKSPACE, "Kiralık_Araçlar.xlsx"))
    demands = load_demands(os.path.join(WORKSPACE, "Desi_talep.xlsx"), selected_date)
    vehicle_by_name = {vehicle.name: vehicle for vehicle in vehicle_types}

    if method not in ("auto", "milp", "greedy"):
        raise ValueError("method 'auto', 'milp' veya 'greedy' olmali.")

    solver_status = "greedy sezgisel"
    if method in ("auto", "milp") and pulp is not None:
        assignments, unmet_routes, flow_decisions, solver_status = solve_global_milp(
            demands,
            vehicle_types,
            vehicle_by_name,
            base_rentals,
            coordinates,
            road_factor,
            allow_consolidation,
        )
    elif method == "milp":
        raise RuntimeError("MILP/global optimum modu icin PuLP gerekli, fakat bu ortamda kurulu degil.")
    else:
        flow_decisions = choose_flow_paths(
            demands,
            vehicle_types,
            vehicle_by_name,
            base_rentals,
            coordinates,
            road_factor,
            allow_consolidation,
        )

        assignments, unmet_routes = build_assignments_for_flows(
            flow_decisions,
            vehicle_types,
            vehicle_by_name,
            base_rentals,
            coordinates,
            road_factor,
        )

    for flow in flow_decisions:
        flow.estimated_cost_tl = estimate_path_cost(
            flow.path,
            flow.demand_desi,
            vehicle_types,
            vehicle_by_name,
            base_rentals,
            coordinates,
            road_factor,
        )

    return OptimizationResult(assignments, unmet_routes, flow_decisions, solver_status)


def write_plan(assignments, output_path):
    # Arac bazli nihai plani CSV olarak yazar.
    # Bu dosya operasyon planina en yakin ciktidir.
    fieldnames = [
        "tarih",
        "orijinal_cikis_tm",
        "orijinal_varis_tm",
        "aktarma_tm",
        "bacak_no",
        "cikis_tm",
        "varis_tm",
        "arac_turu",
        "kaynak",
        "arac_sayisi",
        "yuklenen_desi",
        "kapasite_desi",
        "doluluk_orani",
        "mesafe_km",
        "maliyet_tl",
    ]
    with open(output_path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in assignments:
            writer.writerow(
                {
                    "tarih": item.date,
                    "orijinal_cikis_tm": item.shipment_origin,
                    "orijinal_varis_tm": item.shipment_destination,
                    "aktarma_tm": item.transfer_center,
                    "bacak_no": item.leg_no,
                    "cikis_tm": item.origin,
                    "varis_tm": item.destination,
                    "arac_turu": item.vehicle_type,
                    "kaynak": item.source,
                    "arac_sayisi": item.vehicle_count,
                    "yuklenen_desi": round(item.loaded_desi, 2),
                    "kapasite_desi": round(item.capacity_desi, 2),
                    "doluluk_orani": round(item.utilization, 4),
                    "mesafe_km": round(item.distance_km, 2),
                    "maliyet_tl": round(item.cost_tl, 2),
                }
            )


def write_flow_plan(flow_decisions, output_path):
    # Yuk akisi planini CSV olarak yazar.
    # Bu dosyada her orijinal talebin dogrudan mi aktarmali mi gittigi gorulur.
    fieldnames = [
        "tarih",
        "cikis_tm",
        "varis_tm",
        "talep_desi",
        "secili_yol",
        "aktarma_tm",
        "tahmini_yol_maliyeti_tl",
    ]
    with open(output_path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for flow in flow_decisions:
            writer.writerow(
                {
                    "tarih": flow.date,
                    "cikis_tm": flow.origin,
                    "varis_tm": flow.destination,
                    "talep_desi": round(flow.demand_desi, 2),
                    "secili_yol": " -> ".join(flow.path),
                    "aktarma_tm": flow.transfer_center,
                    "tahmini_yol_maliyeti_tl": (
                        "" if math.isinf(flow.estimated_cost_tl) else round(flow.estimated_cost_tl, 2)
                    ),
                }
            )


def print_summary(result):
    # Terminale kisa performans ozeti basar.
    # Sunumda kullanilan maliyet, doluluk ve aktarma sayisi buradan gelir.
    total_cost = sum(item.cost_tl for item in result.assignments)
    total_demand = sum(flow.demand_desi for flow in result.flow_decisions)
    total_leg_loaded = sum(item.loaded_desi for item in result.assignments)
    total_capacity = sum(item.capacity_desi for item in result.assignments)
    rental_count = sum(item.vehicle_count for item in result.assignments if item.source == "kiralik")
    spot_count = sum(item.vehicle_count for item in result.assignments if item.source == "spot")
    route_count = len({(item.date, item.origin, item.destination) for item in result.assignments})
    consolidated_count = sum(1 for flow in result.flow_decisions if flow.transfer_center)

    print("OPTIMIZASYON OZETI")
    print(f"Cozum modu: {result.solver_status}")
    print(f"Toplam talep desi: {total_demand:,.2f}")
    print(f"Aktarmali tasinan OD sayisi: {consolidated_count}")
    print(f"Planlanan rota sayisi: {route_count}")
    print(f"Kiralik arac sayisi: {rental_count}")
    print(f"Spot arac sayisi: {spot_count}")
    print(f"Toplam arac-bacak yuk desi: {total_leg_loaded:,.2f}")
    print(f"Toplam kapasite: {total_capacity:,.2f}")
    print(f"Ortalama doluluk: {(total_leg_loaded / total_capacity if total_capacity else 0):.2%}")
    print(f"Tahmini toplam maliyet: {total_cost:,.2f} TL")
    print(f"Karsilanamayan rota sayisi: {len(result.unmet_routes)}")


def main():
    # Komut satiri giris noktasi.
    # Ornek:
    #   python -X utf8 logistics_optimizer.py
    #   python -X utf8 logistics_optimizer.py --no-consolidation
    parser = argparse.ArgumentParser(description="Hepsijet anahat kapasite ve maliyet optimizasyonu")
    parser.add_argument("--date", help="Planlanacak tarih, ornek: 2025-12-01. Verilmezse en guncel tarih kullanilir.")
    parser.add_argument("--road-factor", type=float, default=1.25, help="Kus ucusu mesafeyi karayolu mesafesine yaklastirma katsayisi.")
    parser.add_argument("--output", default=os.path.join(WORKSPACE, "optimizasyon_plani.csv"))
    parser.add_argument("--flow-output", default=os.path.join(WORKSPACE, "yuk_akisi_plani.csv"))
    parser.add_argument("--no-consolidation", action="store_true", help="Ara TM secimini kapatir, tum yukleri dogrudan planlar.")
    parser.add_argument(
        "--method",
        choices=["auto", "milp", "greedy"],
        default="auto",
        help="auto: PuLP varsa MILP, yoksa greedy. milp: global optimum ister. greedy: hizli sezgisel.",
    )
    args = parser.parse_args()

    result = optimize(
        args.date,
        args.road_factor,
        allow_consolidation=not args.no_consolidation,
        method=args.method,
    )
    write_plan(result.assignments, args.output)
    write_flow_plan(result.flow_decisions, args.flow_output)
    print_summary(result)
    print(f"Arac plani ciktisi: {args.output}")
    print(f"Yuk akisi ciktisi: {args.flow_output}")


if __name__ == "__main__":
    main()
