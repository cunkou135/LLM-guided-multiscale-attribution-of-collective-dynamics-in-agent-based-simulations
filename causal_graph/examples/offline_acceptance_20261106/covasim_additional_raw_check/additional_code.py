def compute_indicator(data, config):
    rows = data['events']
    return rows.groupby('step')['event_index'].count()
