# Tamil Nadu Districts with Pincodes and Rates
TAMIL_NADU_DISTRICTS = {
    "Chennai": {
        "rate_range": (5000, 25000),
        "pincodes": [f"6000{str(i).zfill(2)}" for i in range(1, 101)]
    },
    "Chengalpattu": {
        "rate_range": (1500, 6000),
        "pincodes": ["603001", "603002", "603003", "603101", "603102", "603103", "603104", "603105", "603201", "603202", "603203", "603204", "603313"]
    },
    "Kanchipuram": {
        "rate_range": (1200, 5000),
        "pincodes": ["631501", "631502", "631551", "631552"]
    },
    "Tiruvallur": {
        "rate_range": (1000, 4000),
        "pincodes": ["602001", "602002", "602003", "602025", "602026"]
    },
    "Coimbatore": {
        "rate_range": (2000, 12000),
        "pincodes": [f"641{str(i).zfill(3)}" for i in range(1, 63)]
    },
    "Erode": {
        "rate_range": (800, 3000),
        "pincodes": ["638001", "638002", "638003", "638101", "638102", "638151", "638316"]
    },
    "Salem": {
        "rate_range": (1000, 4000),
        "pincodes": ["636001", "636002", "636003", "636004", "636005", "636006", "636007", "636008", "636502"]
    },
    "Madurai": {
        "rate_range": (1200, 6000),
        "pincodes": [f"6250{str(i).zfill(2)}" for i in range(1, 21)]
    },
    "Tiruchirappalli": {
        "rate_range": (1000, 4000),
        "pincodes": ["620001", "620002", "620003", "620004", "620005", "621219"]
    },
    "Thanjavur": {
        "rate_range": (800, 2500),
        "pincodes": ["613001", "613002", "613003", "613004", "613005", "614206"]
    },
    "Theni": {
        "rate_range": (700, 2000),
        "pincodes": ["625512", "625513", "625514", "625547"]
    },
    "Dindigul": {
        "rate_range": (700, 2500),
        "pincodes": ["624001", "624002", "624003", "624710"]
    },
    "Vellore": {
        "rate_range": (1000, 4000),
        "pincodes": ["632001", "632002", "632003", "632004", "632005", "632014"]
    },
    "Tirunelveli": {
        "rate_range": (800, 2500),
        "pincodes": ["627001", "627002", "627003", "627862"]
    },
    "Thoothukudi": {
        "rate_range": (800, 3000),
        "pincodes": ["628001", "628002", "628003", "628907"]
    },
    "Sivaganga": {
        "rate_range": (600, 2000),
        "pincodes": ["630001", "630002", "630611"]
    },
    "Ramanathapuram": {
        "rate_range": (600, 2000),
        "pincodes": ["623001", "623002", "623703"]
    },
    "Virudhunagar": {
        "rate_range": (700, 2500),
        "pincodes": ["626001", "626002", "626203"]
    },
    "Namakkal": {
        "rate_range": (800, 2500),
        "pincodes": ["637001", "637002", "637505"]
    },
    "Krishnagiri": {
        "rate_range": (900, 3000),
        "pincodes": ["635001", "635002", "635206"]
    },
    "Dharmapuri": {
        "rate_range": (800, 2500),
        "pincodes": ["636701", "636702", "636813"]
    },
    "Cuddalore": {
        "rate_range": (800, 3000),
        "pincodes": ["607001", "607002", "608907"]
    },
    "Villupuram": {
        "rate_range": (800, 2500),
        "pincodes": ["605601", "605602", "606901"]
    },
    "Nagapattinam": {
        "rate_range": (700, 2000),
        "pincodes": ["611001", "611002", "611108"]
    },
    "Pudukkottai": {
        "rate_range": (700, 2000),
        "pincodes": ["622001", "622002", "622501"]
    },
    "Perambalur": {
        "rate_range": (600, 1800),
        "pincodes": ["621212", "621220"]
    },
    "Ariyalur": {
        "rate_range": (600, 1800),
        "pincodes": ["621704", "621802"]
    },
    "Tiruvarur": {
        "rate_range": (700, 2000),
        "pincodes": ["610001", "610002", "610209"]
    },
    "Nilgiris": {
        "rate_range": (2000, 10000),
        "pincodes": ["643001", "643002", "643243"]
    },
    "Kallakurichi": {
        "rate_range": (800, 2500),
        "pincodes": ["606202", "606308"]
    },
    "Tiruppur": {
        "rate_range": (1200, 6000),
        "pincodes": ["641601", "641602", "641687"]
    }
}

def get_rate_for_pincode(pincode):
    """Get construction rate for a specific pincode"""
    for district, data in TAMIL_NADU_DISTRICTS.items():
        if pincode in data["pincodes"]:
            # Calculate mid-range rate
            min_rate, max_rate = data["rate_range"]
            # Use mid-range for general calculation
            return int((min_rate + max_rate) / 2)
    # Default fallback
    return 1500

def get_district_for_pincode(pincode):
    """Get district name for a pincode"""
    for district, data in TAMIL_NADU_DISTRICTS.items():
        if pincode in data["pincodes"]:
            return district
    return "Unknown"