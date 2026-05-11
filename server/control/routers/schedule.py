import json
from pathlib import Path
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api", tags=["schedule"])

@router.get("/schedule")
async def get_schedule():
    """shared/school_schedule.json 파일을 읽어서 반환합니다."""
    # 현재 파일 위치: server/control/routers/schedule.py
    # 목표 위치: shared/school_schedule.json
    path = Path(__file__).parent.parent.parent.parent / "shared" / "school_schedule.json"
    
    if not path.exists():
        raise HTTPException(status_code=404, detail="Schedule file not found")
        
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading schedule: {str(e)}")
