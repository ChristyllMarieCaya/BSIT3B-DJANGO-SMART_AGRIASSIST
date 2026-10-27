"""Agricultural crop growth modeling and stage calculation engine.

Provides crop-specific agronomic reference data, lifecycle stages,
duration timelines, recommended care activities, and automatic milestone
calculations for registered farm crops.
"""

from datetime import date, timedelta
from typing import Any, Dict, List, Optional


CROP_PROFILES: Dict[str, Dict[str, Any]] = {
    'Rice': {
        'default_duration_days': 115,
        'water_need': 'High (Flooded / saturated soil during vegetative & reproductive)',
        'description': 'Staple cereal grain requiring careful water management and split fertilization.',
        'stages': [
            {
                'name': 'Germination & Seedling',
                'order': 1,
                'start_day': 0,
                'end_day': 20,
                'description': 'Seed germination, nursery establishment, or early seedling emergence.',
                'activities': [
                    'Maintain shallow water (2-3 cm) in seedbed or direct-seeded field',
                    'Inspect for golden apple snail damage and damping-off disease',
                    'Prepare main field with thorough plowing and harrowing',
                ],
                'fertilizer_guidance': 'Basal fertilizer application: complete fertilizer (NPK 14-14-14) or zinc sulfate if zinc deficient.',
                'weather_vulnerability': 'Vulnerable to heavy downpours drowning young seedlings or extreme cold shock.',
            },
            {
                'name': 'Tillering & Vegetative Growth',
                'order': 2,
                'start_day': 21,
                'end_day': 45,
                'description': 'Active tillering and rapid leaf area development determining potential panicle count.',
                'activities': [
                    'Transplant seedlings (if transplanted system) at 20x20 cm hill spacing',
                    'Maintain 3-5 cm water depth',
                    'Perform first weeding 14-21 days after transplanting',
                    'Scout for stem borer, leaf folder, and bacterial leaf blight',
                ],
                'fertilizer_guidance': 'First topdress of urea or ammonium sulfate at 21-25 days after transplanting (active tillering).',
                'weather_vulnerability': 'High heat and stagnant warm water favor bacterial blight; monitor water circulation.',
            },
            {
                'name': 'Panicle Initiation & Stem Elongation',
                'order': 3,
                'start_day': 46,
                'end_day': 70,
                'description': 'Green ring stage inside stem; panicle develops inside the sheath (booting).',
                'activities': [
                    'Maintain continuous water depth of 5-7 cm to protect developing panicles from temperature stress',
                    'Inspect flag leaves for blast lesions or sheath blight',
                    'Avoid mechanical damage to stems during field operations',
                ],
                'fertilizer_guidance': 'Apply second topdress of nitrogen and potash at panicle initiation (critical yield-determining window).',
                'weather_vulnerability': 'Moisture stress during this stage causes irreversible spikelet sterility. Heavy rain delays topdressing.',
            },
            {
                'name': 'Heading & Flowering (Anthesis)',
                'order': 4,
                'start_day': 71,
                'end_day': 85,
                'description': 'Panicle emerges from the boot leaf; pollination and fertilization take place.',
                'activities': [
                    'Keep field well irrigated (5 cm standing water)',
                    'Inspect early morning flowering; avoid chemical sprays during morning pollination (8 AM - 12 PM)',
                    'Scout for rice bug (atangya) which feeds on flowering spikelets',
                ],
                'fertilizer_guidance': 'No fertilizer application during active flowering to avoid disturbing pollination.',
                'weather_vulnerability': 'High winds and heavy rain cause lodging and wash away pollen; temperatures above 35°C induce sterile spikelets.',
            },
            {
                'name': 'Ripening & Maturation',
                'order': 5,
                'start_day': 86,
                'end_day': 115,
                'description': 'Milky, dough, and final yellow grain hardening stages.',
                'activities': [
                    'Drain field water completely 10-14 days before expected harvest date to hasten uniform ripening',
                    'Inspect grain coloration: harvest when 80-85% of grains turn straw-gold',
                    'Prepare threshing, drying mats, and moisture meter equipment',
                ],
                'fertilizer_guidance': 'Fertilizer ceased. Ensure clean water drainage.',
                'weather_vulnerability': 'Heavy rainfall causes lodged mature rice to sprout in the water. Plan harvest around clear forecast windows.',
            },
        ],
    },
    'Corn (Maize)': {
        'default_duration_days': 105,
        'water_need': 'Moderate (high during silking & kernel fill)',
        'description': 'Rapidly growing grain and forage crop highly sensitive to nitrogen timing and moisture during flowering.',
        'stages': [
            {
                'name': 'Emergence & Early Vegetative (V1-V4)',
                'order': 1,
                'start_day': 0,
                'end_day': 20,
                'description': 'Seed germination, root establishment, and first four leaf collars unrolling.',
                'activities': [
                    'Inspect emergence uniformity within 5-7 days after sowing',
                    'Thin excess seedlings to achieve optimal plant population',
                    'Scout for cutworms and fall armyworm (FAW) whorl feeding',
                ],
                'fertilizer_guidance': 'Basal NPK at planting (band placement 5 cm beside and below the seed).',
                'weather_vulnerability': 'Excessive standing water suffocates corn roots within 48 hours; ensure furrows drain freely.',
            },
            {
                'name': 'Rapid Vegetative & Knee-High (V5-V10)',
                'order': 2,
                'start_day': 21,
                'end_day': 45,
                'description': 'Rapid stalk elongation, tassel initiation deep in stalk, and brace root growth.',
                'activities': [
                    'Cultivate and hilling-up around base of plants to support lodging resistance',
                    'Weed thoroughly before canopy closes',
                    'Scout inside whorls for fall armyworm larvae and fecal frass',
                ],
                'fertilizer_guidance': 'Side-dress with urea or ammonium nitrate along row bases; cover lightly with soil.',
                'weather_vulnerability': 'Drought slows vegetative biomass; irrigate furrow every 7-10 days if dry.',
            },
            {
                'name': 'Tasseling & Silking (R1)',
                'order': 3,
                'start_day': 46,
                'end_day': 65,
                'description': 'Tassel sheds pollen and silk emerges from ear shoots. Critical pollination period.',
                'activities': [
                    'Maintain adequate soil moisture; critical 2-week window',
                    'Scout for corn earworm entering through green silks',
                    'Do not disturb plants during peak pollen shedding hours',
                ],
                'fertilizer_guidance': 'Optional light foliar potassium/micronutrient spray if deficiency symptoms appear.',
                'weather_vulnerability': 'Extreme heat (>36°C) desiccates silks and kills pollen, resulting in poor kernel set (scattered grains).',
            },
            {
                'name': 'Grain Fill (Milk to Dough R2-R4)',
                'order': 4,
                'start_day': 66,
                'end_day': 85,
                'description': 'Starch accumulates in kernels; ear silks turn dry and brown.',
                'activities': [
                    'Inspect ears for borers and fungal ear rots',
                    'Maintain moderate soil moisture until dent stage is reached',
                    'Guard against bird and rodent damage',
                ],
                'fertilizer_guidance': 'No further nitrogen; excess late N delays drydown.',
                'weather_vulnerability': 'High winds can snap stalks or cause root lodging; strong storm alerts require ear inspection.',
            },
            {
                'name': 'Physiological Maturity & Drydown (R5-R6)',
                'order': 5,
                'start_day': 86,
                'end_day': 105,
                'description': 'Black layer forms at base of kernel indicating physiological maturity; field drydown follows.',
                'activities': [
                    'Check kernel moisture by fingernail dent and black layer appearance',
                    'Prepare harvest tools, sheller, and sun-drying pavement',
                    'Harvest when moisture drops below 20-25%',
                ],
                'fertilizer_guidance': 'None.',
                'weather_vulnerability': 'Protracted rains cause kernel mold (Aspergillus, Fusarium) on unharvested ears.',
            },
        ],
    },
    'Tomato': {
        'default_duration_days': 95,
        'water_need': 'Moderate to High, requires consistent moisture to avoid blossom end rot',
        'description': 'High-value solanaceous vegetable requiring trellising, pruning, and balanced calcium/potassium.',
        'stages': [
            {
                'name': 'Seedling & Establishment',
                'order': 1,
                'start_day': 0,
                'end_day': 25,
                'description': 'Nursery tray growth, hardening, and transplanting into raised beds.',
                'activities': [
                    'Sow in sterile seedling trays; harden off 5 days before transplanting',
                    'Transplant in late afternoon or cloudy day at 50x75 cm spacing',
                    'Water immediately after transplanting and apply light mulch',
                ],
                'fertilizer_guidance': 'Incorporate compost and complete fertilizer into bed holes prior to planting.',
                'weather_vulnerability': 'Direct heavy rains wash away newly set transplants. Protect with temporary plastic rain-shelters.',
            },
            {
                'name': 'Vegetative Growth & Trellising',
                'order': 2,
                'start_day': 26,
                'end_day': 45,
                'description': 'Stems branch, side suckers emerge, and root system expands.',
                'activities': [
                    'Install bamboo trellises or stakes and tie main stems with soft twine',
                    'Prune lower suckers to maintain single or double leader system',
                    'Scout for aphids, whiteflies, and early leaf spot',
                ],
                'fertilizer_guidance': 'Side-dress balanced NPK with calcium nitrate to build strong cell walls.',
                'weather_vulnerability': 'High humidity with splashing rain spreads bacterial wilt and early blight.',
            },
            {
                'name': 'Flowering & Fruit Setting',
                'order': 3,
                'start_day': 46,
                'end_day': 65,
                'description': 'Yellow flowers open in clusters; pollination and fruit set begin.',
                'activities': [
                    'Maintain uniform drip or furrow watering; avoid wetting foliage',
                    'Gently shake trellis wires at midday to aid self-pollination',
                    'Scout for fruit borers (Helicoverpa) laying eggs near flower buds',
                ],
                'fertilizer_guidance': 'Increase potassium (K) and calcium (Ca); reduce nitrogen to prevent lush leaves with flower drop.',
                'weather_vulnerability': 'Temperature spikes >35°C or night temp >24°C cause flower drop and poor pollination.',
            },
            {
                'name': 'Fruit Development & Sizing',
                'order': 4,
                'start_day': 66,
                'end_day': 80,
                'description': 'Green fruits expand rapidly; skin thickens and seed cavities develop.',
                'activities': [
                    'Inspect fruit calyxes and bottoms for blossom end rot (calcium/water stress symptom)',
                    'Prune yellowing lower leaves to improve air circulation beneath the canopy',
                    'Keep watering steady; fluctuating wet-dry cycles induce fruit cracking',
                ],
                'fertilizer_guidance': 'Apply potassium sulfate or calcium-potassium foliar spray.',
                'weather_vulnerability': 'Sudden heavy rain after a dry spell causes immediate fruit splitting and skin cracking.',
            },
            {
                'name': 'Ripening & Harvesting',
                'order': 5,
                'start_day': 81,
                'end_day': 95,
                'description': 'Fruit turns from breaker (blush) to pink, light red, and full red maturity.',
                'activities': [
                    'Harvest at breaker stage for distant transport or full red for immediate market',
                    'Use clean shears and gently place in padded plastic crates',
                    'Continue selective harvesting every 2-3 days',
                ],
                'fertilizer_guidance': 'Maintain light maintenance watering; no heavy feeding.',
                'weather_vulnerability': 'High temperature speeds over-ripening; harvest early in morning while fruit is cool.',
            },
        ],
    },
    'Eggplant': {
        'default_duration_days': 110,
        'water_need': 'Moderate, consistent soil moisture',
        'description': 'Prolific solanaceous vegetable with continuous fruiting over multiple months.',
        'stages': [
            {
                'name': 'Seedling & Transplanting',
                'order': 1,
                'start_day': 0,
                'end_day': 30,
                'description': 'Nursery management and transplanting healthy 4-leaf seedlings.',
                'activities': [
                    'Transplant in raised beds at 75x100 cm spacing',
                    'Drench root zone with compost tea or starter solution',
                    'Inspect for flea beetles and cutworms',
                ],
                'fertilizer_guidance': 'Basal complete fertilizer (14-14-14) plus organic matter in planting furrows.',
                'weather_vulnerability': 'Seedlings sensitive to waterlogging; provide good drainage ditches.',
            },
            {
                'name': 'Vegetative & Branching',
                'order': 2,
                'start_day': 31,
                'end_day': 55,
                'description': 'Main stem develops thick woody base; strong lateral branches form.',
                'activities': [
                    'Stake plants with sturdy wooden or bamboo posts',
                    'Weed around base and hill up soil',
                    'Inspect under leaves for eggplant fruit and shoot borer (EFSB) entries',
                ],
                'fertilizer_guidance': 'Side-dress with urea/ammonium sulfate 3 weeks after transplanting.',
                'weather_vulnerability': 'Tolerates heat well; prolonged cloudy days slow down branching.',
            },
            {
                'name': 'Flowering & Early Fruit Set',
                'order': 3,
                'start_day': 56,
                'end_day': 75,
                'description': 'Purple star-shaped flowers blossom at node joints; fruit calyxes enlarge.',
                'activities': [
                    'Prune damaged shoots displaying wilted tips (shoot borer indicator)',
                    'Maintain uniform soil moisture during flower setting',
                    'Check for red spider mites and leafhoppers',
                ],
                'fertilizer_guidance': 'Side-dress with high-potassium fertilizer (14-14-14 or 16-16-16).',
                'weather_vulnerability': 'Heavy rainfall can knock off blossoms; avoid overwatering.',
            },
            {
                'name': 'Fruit Sizing & Harvest Period',
                'order': 4,
                'start_day': 76,
                'end_day': 110,
                'description': 'Eggplants reach glossy, firm market size; continuous harvests begin.',
                'activities': [
                    'Harvest with sharp clippers leaving 2 cm stem with calyx intact',
                    'Harvest every 3-4 days to stimulate further flower emergence',
                    'Remove overripe, dull-colored fruit immediately',
                ],
                'fertilizer_guidance': 'Light split fertilizer every 2-3 weeks to maintain continuous fruit yield.',
                'weather_vulnerability': 'Excess rain promotes fruit anthracnose; keep fruit elevated off the bare soil.',
            },
        ],
    },
    'Onion': {
        'default_duration_days': 120,
        'water_need': 'Moderate in vegetative; dry during maturity',
        'description': 'Bulb vegetable requiring weed-free beds and strict moisture cessation prior to harvest.',
        'stages': [
            {
                'name': 'Seedling & Establishment',
                'order': 1,
                'start_day': 0,
                'end_day': 35,
                'description': 'Transplanting slender seedlings into well-pulverized beds.',
                'activities': [
                    'Transplant 40-45 day old seedlings at 10x15 cm spacing',
                    'Apply rice straw mulch to conserve moisture and suppress weeds',
                    'Maintain shallow, frequent irrigation',
                ],
                'fertilizer_guidance': 'Apply basal fertilizer with sulfur and phosphorus to encourage root development.',
                'weather_vulnerability': 'Delicate shallow roots wash out in torrential rains.',
            },
            {
                'name': 'Vegetative Leaf Production',
                'order': 2,
                'start_day': 36,
                'end_day': 70,
                'description': 'Each new leaf produced will eventually form one fleshy bulb ring.',
                'activities': [
                    'Keep plot strictly weed-free (onions compete poorly with weeds)',
                    'Scout for thrips inside leaf sheaths',
                    'Inspect for purple blotch and anthracnose',
                ],
                'fertilizer_guidance': 'Side-dress nitrogen in 2 splits (at 20 and 40 days after transplanting).',
                'weather_vulnerability': 'Hot, dry winds favor rapid thrips multiplication.',
            },
            {
                'name': 'Bulb Initiation & Enlargement',
                'order': 3,
                'start_day': 71,
                'end_day': 100,
                'description': 'Bulb expands at the base of the leaf stems.',
                'activities': [
                    'Maintain steady moisture so bulbs expand smoothly without splitting',
                    'Stop all nitrogen fertilizer to prevent thick-necked, un-storable bulbs',
                    'Apply potassium-rich fertilizer',
                ],
                'fertilizer_guidance': 'Apply potassium sulfate; stop nitrogen completely.',
                'weather_vulnerability': 'Flooding during bulking leads to neck rot and bulb decay.',
            },
            {
                'name': 'Maturation & Curing',
                'order': 4,
                'start_day': 101,
                'end_day': 120,
                'description': 'Tops soften, bend over (fall down), and outer scales dry.',
                'activities': [
                    'Withhold all irrigation 10-14 days before harvest',
                    'Harvest when 50-70% of tops have fallen naturally',
                    'Field-cure under shade for 7-10 days before clipping necks',
                ],
                'fertilizer_guidance': 'None.',
                'weather_vulnerability': 'Rains during curing ruin the outer protective skin and trigger rot in storage.',
            },
        ],
    },
    'Pepper (Chili / Bell)': {
        'default_duration_days': 90,
        'water_need': 'Moderate, well-drained soil',
        'description': 'Capsicum crop yielding spicy or sweet pods over multiple flushes.',
        'stages': [
            {
                'name': 'Nursery & Seedling Establishment',
                'order': 1,
                'start_day': 0,
                'end_day': 25,
                'description': 'Germination and early growth in seedling trays before transplanting.',
                'activities': [
                    'Transplant stocky seedlings at 50x50 cm spacing into raised beds',
                    'Mulch with straw or plastic mulch to stabilize soil temperature',
                    'Inspect for damping-off and broad mites',
                ],
                'fertilizer_guidance': 'Basal compost plus complete fertilizer in planting holes.',
                'weather_vulnerability': 'Seedlings are delicate; protect from pounding rains.',
            },
            {
                'name': 'Vegetative Branching',
                'order': 2,
                'start_day': 26,
                'end_day': 45,
                'description': 'Plants produce multiple branching forks where flowers develop.',
                'activities': [
                    'Provide light staking to support heavy pod-bearing branches',
                    'Scout for thrips causing crinkled, upward-curling leaf margins',
                    'Inspect for anthracnose lesions on stems',
                ],
                'fertilizer_guidance': 'Side-dress complete fertilizer plus magnesium/calcium.',
                'weather_vulnerability': 'Standing water causes sudden wilt within 24 hours.',
            },
            {
                'name': 'Flowering & Fruit Setting',
                'order': 3,
                'start_day': 46,
                'end_day': 65,
                'description': 'Small white flowers appear at stem forks and set young pods.',
                'activities': [
                    'Maintain consistent irrigation; avoid moisture swings',
                    'Scout for pepper fruit fly and anthracnose spots on green pods',
                ],
                'fertilizer_guidance': 'Side-dress high-potash fertilizer to support pod firmness.',
                'weather_vulnerability': 'Temperatures above 34°C cause flower and fruitlet drop.',
            },
            {
                'name': 'Pod Maturation & Harvest',
                'order': 4,
                'start_day': 66,
                'end_day': 90,
                'description': 'Pods reach mature green or full vibrant red/yellow color.',
                'activities': [
                    'Harvest pods with stem attached using clean clippers',
                    'Pick mature pods frequently to stimulate continuous flower production',
                    'Sort and pack in well-ventilated crates',
                ],
                'fertilizer_guidance': 'Maintain light split topdressing every 2 weeks.',
                'weather_vulnerability': 'Sunscald occurs during extreme heat on exposed fruits; maintain leaf canopy.',
            },
        ],
    },
    'Potato': {
        'default_duration_days': 100,
        'water_need': 'Moderate, consistent moisture',
        'description': 'Tuber crop thriving in cool highland climates or cool winter lowlands.',
        'stages': [
            {
                'name': 'Sprouting & Emergence',
                'order': 1,
                'start_day': 0,
                'end_day': 20,
                'description': 'Seed tuber sprouts emerge from the soil.',
                'activities': [
                    'Plant certified disease-free sprouted seed tubers at 30x75 cm spacing',
                    'Inspect for uniform emergence and seed piece decay',
                ],
                'fertilizer_guidance': 'Basal phosphorus and potassium in furrow; moderate initial nitrogen.',
                'weather_vulnerability': 'Waterlogged soil causes seed pieces to rot before emergence.',
            },
            {
                'name': 'Vegetative Canopy & Hilling-Up',
                'order': 2,
                'start_day': 21,
                'end_day': 40,
                'description': 'Lush foliage develops; stolons initiate beneath the soil.',
                'activities': [
                    'Hill up loose soil around plant bases to provide space for tubers and prevent greening',
                    'Scout for potato tuber moth and late blight lesions',
                ],
                'fertilizer_guidance': 'Side-dress nitrogen and potassium prior to hilling-up.',
                'weather_vulnerability': 'Cool, humid, foggy weather favors rapid late blight epidemics.',
            },
            {
                'name': 'Tuber Initiation & Bulking',
                'order': 3,
                'start_day': 41,
                'end_day': 80,
                'description': 'Stolon tips swell into potatoes; rapid starch accumulation.',
                'activities': [
                    'Maintain regular, even irrigation to prevent knobby, misshapen tubers',
                    'Perform final light hilling to ensure all tubers remain covered from sunlight',
                    'Inspect leaves for blight and potato virus symptoms',
                ],
                'fertilizer_guidance': 'High potassium application; discontinue nitrogen.',
                'weather_vulnerability': 'Soil temperatures >28°C stop tuber bulking.',
            },
            {
                'name': 'Maturation & Skin Setting',
                'order': 4,
                'start_day': 81,
                'end_day': 100,
                'description': 'Vines yellow and die back; tuber skins harden for storage.',
                'activities': [
                    'Stop irrigation 10-14 days before digging',
                    'Cut vines (de-haulming) 7-10 days before harvest to firm tuber skins',
                    'Dig carefully with fork or mechanical digger to avoid bruising',
                ],
                'fertilizer_guidance': 'None.',
                'weather_vulnerability': 'Heavy rains before harvest saturate soil and encourage bacterial soft rot.',
            },
        ],
    },
    'Cabbage': {
        'default_duration_days': 85,
        'water_need': 'High, uniform moisture',
        'description': 'Cool-season brassica forming dense leafy heads.',
        'stages': [
            {
                'name': 'Seedling & Establishment',
                'order': 1,
                'start_day': 0,
                'end_day': 25,
                'description': 'Transplanting sturdy 4-5 leaf seedlings.',
                'activities': [
                    'Transplant at 40x50 cm spacing into rich, well-drained beds',
                    'Protect young transplants with netting against diamondback moth',
                ],
                'fertilizer_guidance': 'Basal compost plus complete fertilizer high in phosphorus.',
                'weather_vulnerability': 'Heat stress causes premature bolting (flowering).',
            },
            {
                'name': 'Cupping & Frame Building',
                'order': 2,
                'start_day': 26,
                'end_day': 50,
                'description': 'Outer wrapper leaves enlarge and center leaves begin cupping inward.',
                'activities': [
                    'Weed thoroughly before head closes',
                    'Scout for diamondback moth larvae, cabbage loopers, and clubroot',
                ],
                'fertilizer_guidance': 'Side-dress with nitrogen and potassium.',
                'weather_vulnerability': 'Heavy rains splash soil into head crevices.',
            },
            {
                'name': 'Head Formation & Firming',
                'order': 3,
                'start_day': 51,
                'end_day': 70,
                'description': 'Inner leaves tightly overlap, swelling into a firm, solid head.',
                'activities': [
                    'Maintain steady irrigation; fluctuating water causes heads to burst',
                    'Scout for black rot (V-shaped leaf yellowing) and aphids',
                ],
                'fertilizer_guidance': 'Light potassium application to strengthen head density.',
                'weather_vulnerability': 'Sudden downpour causes mature tight heads to split open.',
            },
            {
                'name': 'Head Maturity & Harvest',
                'order': 4,
                'start_day': 71,
                'end_day': 85,
                'description': 'Heads are rock-hard to touch and reach target market weight.',
                'activities': [
                    'Harvest by cutting stem close to head base, keeping 2-3 protective wrapper leaves',
                    'Handle gently to avoid bruising outer leaves',
                ],
                'fertilizer_guidance': 'None.',
                'weather_vulnerability': 'Prolonged field holding in rain triggers head rotting.',
            },
        ],
    },
}

# Generic profile for any unlisted crop
DEFAULT_GENERIC_PROFILE: Dict[str, Any] = {
    'default_duration_days': 90,
    'water_need': 'Moderate',
    'description': 'Standard agricultural crop lifecycle.',
    'stages': [
        {
            'name': 'Seedling & Establishment',
            'order': 1,
            'start_day': 0,
            'end_day': 20,
            'description': 'Emergence and root system establishment.',
            'activities': [
                'Ensure gentle, regular moisture',
                'Protect from pests and weeds',
                'Inspect seedling vigor',
            ],
            'fertilizer_guidance': 'Basal balanced fertilizer or compost.',
            'weather_vulnerability': 'Sensitive to heavy flooding and extreme temperature shocks.',
        },
        {
            'name': 'Vegetative Growth',
            'order': 2,
            'start_day': 21,
            'end_day': 45,
            'description': 'Active leaf, stem, and root expansion.',
            'activities': [
                'Weed and cultivate soil around roots',
                'Monitor for insect pests and foliage diseases',
                'Maintain regular irrigation',
            ],
            'fertilizer_guidance': 'Side-dress with nitrogen-rich fertilizer.',
            'weather_vulnerability': 'Drought stress retards vegetative frame development.',
        },
        {
            'name': 'Reproductive / Flowering / Bulking',
            'order': 3,
            'start_day': 46,
            'end_day': 70,
            'description': 'Flowering, fruit setting, or storage organ development.',
            'activities': [
                'Maintain steady moisture levels',
                'Inspect for fruit and blossom pests',
                'Avoid severe mechanical disturbance',
            ],
            'fertilizer_guidance': 'Apply potassium- and phosphorus-balanced fertilizer.',
            'weather_vulnerability': 'Extreme heat or high winds damage flowers and pollination.',
        },
        {
            'name': 'Maturity & Harvest',
            'order': 4,
            'start_day': 71,
            'end_day': 90,
            'description': 'Final ripening and harvest preparation.',
            'activities': [
                'Reduce irrigation to prepare for harvest',
                'Check readiness indicators (color, firmness, moisture)',
                'Prepare clean harvest and storage equipment',
            ],
            'fertilizer_guidance': 'Cease fertilizer application.',
            'weather_vulnerability': 'Rains during maturity cause spoilage or grain sprouting.',
        },
    ],
}


def normalize_crop_name(name: str) -> str:
    """Match crop name to standard profile keys."""
    raw = (name or '').strip().lower()
    for key in CROP_PROFILES.keys():
        if key.lower() in raw or raw in key.lower():
            return key
    # Common aliases
    if 'corn' in raw or 'maize' in raw:
        return 'Corn (Maize)'
    if 'palay' in raw or 'rice' in raw or 'paddy' in raw:
        return 'Rice'
    if 'tomato' in raw or 'kamatis' in raw:
        return 'Tomato'
    if 'eggplant' in raw or 'talong' in raw:
        return 'Eggplant'
    if 'chili' in raw or 'pepper' in raw or 'sili' in raw:
        return 'Pepper (Chili / Bell)'
    if 'onion' in raw or 'sibuyas' in raw:
        return 'Onion'
    if 'potato' in raw or 'patatas' in raw:
        return 'Potato'
    if 'cabbage' in raw or 'repolyo' in raw:
        return 'Cabbage'
    return name.strip() or 'Custom Crop'


def get_crop_profile(crop_name: str) -> Dict[str, Any]:
    """Retrieve agronomic profile with stages for given crop."""
    matched = normalize_crop_name(crop_name)
    return CROP_PROFILES.get(matched, DEFAULT_GENERIC_PROFILE)


def calculate_crop_growth(
    crop_name: str,
    planting_date: date,
    custom_duration: Optional[int] = None,
    current_date: Optional[date] = None,
) -> Dict[str, Any]:
    """Calculate days since planting, current growth stage, progress percentage,

    upcoming milestones, and estimated harvest date.
    """
    if current_date is None:
        current_date = date.today()

    profile = get_crop_profile(crop_name)
    total_duration = custom_duration or profile.get('default_duration_days', 90)

    # Days since planting (clamped to 0 minimum)
    days_since_planting = (current_date - planting_date).days
    effective_days = max(0, days_since_planting)

    # Lifecycle overall progress percentage (0 to 100)
    overall_progress = min(100.0, max(0.0, (effective_days / total_duration) * 100.0))

    # Calculate stages and scaling factor if custom duration differs from default
    stages_def = profile.get('stages', DEFAULT_GENERIC_PROFILE['stages'])
    default_duration = profile.get('default_duration_days', 90)
    scale = total_duration / default_duration if default_duration > 0 else 1.0

    current_stage = None
    stage_progress = 0.0
    milestones: List[Dict[str, Any]] = []

    for idx, s in enumerate(stages_def):
        s_start = int(round(s['start_day'] * scale))
        s_end = int(round(s['end_day'] * scale))
        s_start_date = planting_date + timedelta(days=s_start)
        s_end_date = planting_date + timedelta(days=s_end)

        is_current = (s_start <= effective_days <= s_end)
        is_past = effective_days > s_end
        is_future = effective_days < s_start

        if is_current:
            current_stage = {
                'name': s['name'],
                'order': s['order'],
                'start_day': s_start,
                'end_day': s_end,
                'start_date': s_start_date,
                'end_date': s_end_date,
                'description': s['description'],
                'activities': s.get('activities', []),
                'fertilizer_guidance': s.get('fertilizer_guidance', ''),
                'weather_vulnerability': s.get('weather_vulnerability', ''),
            }
            stage_duration = max(1, s_end - s_start)
            days_in_stage = max(0, effective_days - s_start)
            stage_progress = min(100.0, max(0.0, (days_in_stage / stage_duration) * 100.0))

        milestones.append({
            'order': s['order'],
            'name': s['name'],
            'start_day': s_start,
            'end_day': s_end,
            'start_date': s_start_date,
            'end_date': s_end_date,
            'days_remaining': max(0, s_start - effective_days) if is_future else 0,
            'is_current': is_current,
            'is_past': is_past,
            'is_future': is_future,
            'description': s['description'],
            'activities': s.get('activities', []),
            'fertilizer_guidance': s.get('fertilizer_guidance', ''),
            'weather_vulnerability': s.get('weather_vulnerability', ''),
        })

    # If beyond total duration, current stage is final stage marked completed
    if current_stage is None and stages_def:
        final_s = milestones[-1]
        current_stage = {
            'name': f"{final_s['name']} (Ready for Harvest)",
            'order': final_s['order'],
            'start_day': final_s['start_day'],
            'end_day': final_s['end_day'],
            'start_date': final_s['start_date'],
            'end_date': final_s['end_date'],
            'description': 'Crop has reached or exceeded expected maturity duration.',
            'activities': ['Perform final maturity inspection', 'Harvest promptly to avoid field loss'],
            'fertilizer_guidance': 'Cease fertilizer application.',
            'weather_vulnerability': 'Harvest quickly before impending rains cause lodging or rot.',
        }
        stage_progress = 100.0

    estimated_harvest_date = planting_date + timedelta(days=total_duration)
    days_until_harvest = max(0, (estimated_harvest_date - current_date).days)

    return {
        'crop_name': crop_name,
        'planting_date': planting_date,
        'current_date': current_date,
        'days_since_planting': days_since_planting,
        'total_duration_days': total_duration,
        'overall_progress_percentage': round(overall_progress, 1),
        'stage_progress_percentage': round(stage_progress, 1),
        'current_stage': current_stage,
        'estimated_harvest_date': estimated_harvest_date,
        'days_until_harvest': days_until_harvest,
        'milestones': milestones,
        'water_need': profile.get('water_need', 'Moderate'),
        'description': profile.get('description', ''),
    }
