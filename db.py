from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY

supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)

def add_punishment(user_id, ip, reason, base_days, points, multiplier, total_points_at_ban):
    final_duration = int(base_days * multiplier)

    current_stage = get_user_stage(user_id, reason)
    current_stage = int(current_stage)

    data = {
        "user_id": user_id,
        "ip": ip,
        "reason": reason,
        "base_days": int(base_days),
        "points": int(points),
        "multiplier": float(multiplier),
        "final_duration": final_duration,
        "stage": current_stage,
        "total_points_at_ban": float(total_points_at_ban)
    }

    supabase_client.from_('punishments').insert(data).execute()
    return final_duration

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

    from datetime import datetime
    return [
        {
            "points": entry["points"],
            "timestamp": datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00"))
        }
        for entry in response.data
    ]

def calculate_total_decayed_points(infractions, current_time, test_mode=False):
    DECAY_PERIOD = 15 if test_mode else 60 * 60 * 24 * 60  # 600s = 10min for testing, 60d in prod
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

def get_latest_punishment(username):
    result = (
        supabase_client
        .from_('punishments')
        .select('created_at, points, total_points_at_ban')
        .eq('user_id', username)
        .order('created_at', desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None
