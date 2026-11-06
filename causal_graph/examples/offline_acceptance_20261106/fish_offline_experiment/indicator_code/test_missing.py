def compute_indicator(data, config):
    return data['agent_states'].groupby('step')['intentionally_absent'].mean()
