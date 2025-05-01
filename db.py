from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY

supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)

def add_punishment(user_id, ip, reason, base_days, points, multiplier):
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
        "stage": current_stage
    }

    supabase_client.from_('punishments').insert(data).execute()
    return final_duration

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
    result = supabase_client.from_('punishments').select("points").eq("user_id", user_id).execute()
    return sum(entry["points"] for entry in result.data)

def get_all_punishment_options():
    result = supabase_client.from_('catalog').select("*").order("stage", desc=False).execute()
    return result.data

def get_catalog_punishment(reason, stage):
    print(f"Attempting to fetch punishment with reason: '{reason}' and stage: {stage}")
    result = (
        supabase_client
        .from_('catalog')
        .select('*')
        .eq('reason', reason)
        .eq('stage', stage)
        .limit(1)
        .execute()
    )

    print(f"Result data: {result.data}")
    if result.data and len(result.data) > 0:
        return result.data[0]
    else:
        print(f"No matching catalog entry found for reason: '{reason}' and stage: {stage}")
        return None

def get_user_offense_count(user_id):
    response = supabase_client.from_('punishments').select('id').eq('user_id', user_id).execute()
    return len(response.data)
