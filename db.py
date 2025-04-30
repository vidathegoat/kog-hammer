from supabase import create_supabase_client
from config import SUPABASE_URL, SUPABASE_KEY

supabase_client = create_supabase_client(SUPABASE_URL, SUPABASE_KEY)

def add_punishment(user_id, reason, base_days, points, multiplier):
    final_duration = int(base_days * multiplier)
    data = {
        "user_id": user_id,
        "reason": reason,
        "base_days": base_days,
        "points": points,
        "multiplier": multiplier,
        "final_duration": final_duration,
    }
    supabase.table("punishments").insert(data).execute()
    return final_duration

def get_user_points(user_id):
    result = supabase.table("punishments").select("points").eq("user_id", user_id).execute()
    return sum(entry["points"] for entry in result.data)