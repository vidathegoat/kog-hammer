from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY
from dateutil import parser

supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)

def add_punishment(user_id, ip, reason,
                   base_days, points, multiplier, total_pts_at_ban,
                   *, explicit_stage: int | None = None):

    stage = (explicit_stage
             if explicit_stage is not None
             else get_user_stage(user_id, reason))

    data = {
        "user_id": user_id,
        "ip": ip,
        "reason": reason,
        "base_days": base_days,
        "points": points,
        "multiplier": multiplier,
        "final_duration": int(base_days * multiplier),
        "stage": stage,
        "total_points_at_ban": total_pts_at_ban,
    }
    supabase_client.from_("punishments").insert(data).execute()

def log_infraction(user_id, points, context, source="automated"):
    data = {
        "user_id": user_id,
        "points": float(points),
        "context": context,
        "source": source
    }
    supabase_client.from_('infractions').insert(data).execute()

def get_user_stage(user_id, reason):
    response = supabase_client.from_('punishments').select('stage') \
        .eq('user_id', user_id) \
        .eq('reason', reason) \
        .order('stage', desc=True) \
        .limit(1) \
        .execute()

    if response.data and response.data[0]['stage'] is not None:
        return int(response.data[0]['stage']) + 1
    else:
        return 1

def get_user_points(user_id):
    result = supabase_client.from_('infractions').select("points").eq("user_id", user_id).execute()
    return sum(entry["points"] for entry in result.data) if result.data else 0


def fetch_user_infractions(user_id):
    response = supabase_client.from_('infractions').select('*').eq('user_id', user_id).execute()
    if not response.data:
        return []

    return [
        {
            "points": entry["points"],
            "timestamp": parser.isoparse(entry["timestamp"])
        }
        for entry in response.data
    ]

def calculate_total_decayed_points(infractions, current_time, test_mode=False):
    DECAY_PERIOD = 15 if test_mode else 60 * 60 * 24 * 60  # 15s for testing, 60d in prod
    DECAY_FACTOR = 0.95

    total = 0.0
    for entry in infractions:
        age_seconds = (current_time - entry['timestamp']).total_seconds()
        decay_periods = int(age_seconds // DECAY_PERIOD)
        decayed = entry['points'] * (DECAY_FACTOR ** decay_periods)
        total += decayed
    return round(total, 2)

def get_all_punishment_options():
    result = supabase_client.from_('catalog').select("*").order("stage", desc=False).execute()
    return result.data

def get_catalog_punishment(reason, stage):
    result = (
        supabase_client
        .from_('catalog')
        .select('*')
        .eq('reason', reason)
        .eq('stage', stage)
        .limit(1)
        .execute()
    )
    if result.data and len(result.data) > 0:
        return result.data[0]
    return None

def get_latest_punishment(username, reason):
    result = (
        supabase_client
        .from_('punishments')
        .select('*')
        .eq('user_id', username)
        .eq('reason', reason)
        .order('created_at', desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None
