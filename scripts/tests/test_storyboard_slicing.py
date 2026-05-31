import pytest
from pathlib import Path
from services.youtube_transcript import _get_target_timestamps, _get_heatmap_peaks

def test_get_heatmap_peaks():
    # Mock heatmap data
    heatmap = [
        {"start_time": 10.0, "end_time": 20.0, "value": 0.5},
        {"start_time": 30.0, "end_time": 40.0, "value": 0.9},  # Peak 1 (value 0.9, mid 35)
        {"start_time": 50.0, "end_time": 60.0, "value": 0.2},
        {"start_time": 70.0, "end_time": 80.0, "value": 0.95}, # Peak 2 (value 0.95, mid 75)
    ]
    
    peaks = _get_heatmap_peaks(heatmap, duration_sec=100.0, max_peaks=2)
    assert len(peaks) == 2
    # Should sort Peak 2 first, Peak 1 second, but return sorted chronologically: [35.0, 75.0]
    assert peaks == [35.0, 75.0]

def test_get_target_timestamps_with_heatmap():
    chapters = [
        {"start_time": 0.0, "end_time": 50.0, "title": "Ch1"},
        {"start_time": 50.0, "end_time": 100.0, "title": "Ch2"},
    ]
    heatmap = [
        {"start_time": 30.0, "end_time": 40.0, "value": 0.95}, # Peak at 35.0
    ]
    
    ts = _get_target_timestamps(duration_sec=100.0, chapters=chapters, heatmap=heatmap)
    # Should contain chapter static points + heatmap peak
    assert 35.0 in ts
    assert len(ts) > 0
