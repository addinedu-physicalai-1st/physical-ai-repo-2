# 추종 시작 시 perception/follow 노드에 전달되는 target 정보.

string teacher_id           # User.id UUID 문자열
string teacher_name         # 표시용 이름
float32[] embedding         # InsightFace 512-d (L2-normalized)
int64 ts_ms
