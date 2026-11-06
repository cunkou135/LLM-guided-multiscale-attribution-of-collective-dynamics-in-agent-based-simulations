import json
import pandas as pd
def compute_indicator(data, config):
    rows = data['raw_frames']
    return pd.DataFrame({'step': rows['step'], 'value': rows['frame_json'].map(lambda x: len(json.loads(x)['positions']))})
