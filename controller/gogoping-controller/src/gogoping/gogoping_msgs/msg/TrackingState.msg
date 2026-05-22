# follow_node 가 5 Hz publish.

string mode                 # "idle" | "searching" | "tracking" | "lost"
bool matched
float32 distance_m          # LiDAR 측정. NaN = 미측정
float32 angle_deg           # 카메라 frame 방위
int32 bbox_size_px
int32 bbox_x1
int32 bbox_y1
int32 bbox_x2
int32 bbox_y2
int32 track_id              # ByteTrack track_id. 0 = 없음
float32 reid_sim            # 마지막 ReID 유사도. NaN = 미측정
string teacher_id
int64 ts_ms
