"""Mesa SolaraViz interface; the simulation itself is the headless RunSession."""
import copy
import os
from pathlib import Path
import threading

import numpy as np
import solara
from mesa import Model

from simulations.common.runner import RunSession, load, _parameter_target
from visualization.layout import LaboratoryLayout,ResetSceneViewport
Layout = LaboratoryLayout


class VisualRun(Model):
    def __init__(self, config, primary, secondary):
        c = copy.deepcopy(config)
        if c['model'].startswith('schelling'):
            c['parameters'].update({('homophily_mean' if c['model'] == 'schelling_extended' else 'homophily'): primary, 'density': secondary})
        elif c['model']=='fish':
            c['parameters']['population']['count']=int(primary)
            c['parameters']['fish']['N_p']=int(secondary)
        else:
            c['parameters'].update(beta=primary, pop_infected=int(secondary))
        super().__init__(rng=c['seed'])
        self.lock = threading.RLock()
        self.session = RunSession(c, live_snapshots=True)
        self.history = []
        self.remember()

    def remember(self):
        m = self.session.model
        if self.session.config['model'].startswith('schelling'):
            summary = m.summary()
            population = summary['population']
            score = summary['happy'] / population if population else 0
            similarity = summary['same_neighbors'] / summary['neighbors'] if summary['neighbors'] else 0
            self.history.append((self.session.completed, score, similarity))
        elif self.session.config['model']=='fish':
            summary=m.summary()
            self.history.append((self.session.completed,summary['population'],summary['predators']))
        else:
            summary = m.summary()
            self.history.append((self.session.completed, summary['infectious'], summary['diagnosed']))

    def step(self):
        with self.lock:
            if not self.session.closed:
                self.session.advance()
                self.remember()
            self.running = not self.session.closed

    def close(self):
        with self.lock:
            self.session.close()
            self.running = False


from simulations.common.trajectory_api import Trajectory
from visualization.figures import (figure_config, interactive_grid, interactive_schelling_curves,
                                   interactive_covasim, publication_figure, export_publication,
                                   intervention_schedule, LAYERS, INTERVENTIONS)


def _model(config):
    p = config['parameters']
    if config['model'].startswith('schelling'):
        primary = p['homophily_mean'] if config['model'] == 'schelling_extended' else p['homophily']
        secondary = p['density']
    elif config['model']=='fish':
        primary,secondary=p['population']['count'],p['fish']['N_p']
    else:
        primary, secondary = p['beta'], p['pop_infected']
    return VisualRun(config, primary, secondary)


@solara.component
def Page():
    initial_path = os.environ['ABMS_CONFIG']
    current = solara.use_reactive(solara.use_memo(lambda: _model(load(initial_path)), []))
    config_path, set_config_path = solara.use_state(initial_path)
    pending, set_pending = solara.use_state({})
    mode, set_mode = solara.use_state('实时实验')
    replay_path, set_replay_path = solara.use_state('')
    replay_directory, set_replay_directory = solara.use_state('')
    selected_index, set_selected_index = solara.use_state(0)
    follow, set_follow = solara.use_state(True)
    playing = solara.use_reactive(False)
    revision = solara.use_reactive(0)
    selected_resident, set_selected_resident = solara.use_state(None)
    show_unhappy, set_show_unhappy = solara.use_state(False)
    show_similarity, set_show_similarity = solara.use_state(False)
    publication, set_publication = solara.use_state(False)
    message, set_message = solara.use_state('')
    exported, set_exported = solara.use_state('')
    window_start, set_window_start = solara.use_state(0)
    selected_uid, set_selected_uid = solara.use_state(-1)
    capture_message, set_capture_message = solara.use_state('')
    analysis_open, set_analysis_open = solara.use_state(False)
    parameter_search,set_parameter_search=solara.use_state('')
    loaded_path, set_loaded_path = solara.use_state(initial_path)
    model = current.value
    cfg = model.session.config
    revision.value  # Subscribe to complete, durably saved sampling steps.
    directory = replay_directory if mode == '历史回放' and replay_directory else str(model.session.out)
    trajectory = Trajectory(directory)
    steps = trajectory.available_steps()
    index = len(steps)-1 if follow and mode == '实时实验' else min(selected_index, len(steps)-1)
    selected_step = steps[index]
    actual_config = trajectory.configuration()
    display_config = actual_config['visualization'].get('display', {})
    interval = display_config.get('play_interval_seconds', .35)
    settings = figure_config(display_config.get('figure_config', 'configs/figures.yaml'))

    def cleanup():
        return model.close
    solara.use_effect(cleanup, [model])

    def play(cancel):
        if not playing.value:
            return
        local_index = index
        while not cancel.is_set() and playing.value:
            if mode == '实时实验':
                if model.session.closed:
                    playing.set(False)
                    return
                model.step()
                revision.set(revision.value+1)
            else:
                if local_index >= len(steps)-1:
                    playing.set(False)
                    return
                local_index += 1
                set_selected_index(local_index)
            if cancel.wait(interval):
                return
    solara.use_thread(play, dependencies=[playing.value, model, mode], intrusive_cancel=False)

    def replace(path, overrides=None):
        playing.set(False)
        model.close()
        try:
            new_config = load(path)
            for key, value in (overrides or {}).items():
                if key == 'seed':
                    new_config['seed'] = value
                else:
                    node,field,_=_parameter_target(new_config,key)
                    node[field]=value
            replacement = _model(new_config)
            current.set(replacement)
            set_config_path(path)
            set_loaded_path(path)
            set_pending({})
            set_selected_index(0)
            set_follow(True)
            set_mode('实时实验')
            set_exported('')
            set_selected_resident(None)
            set_selected_uid(-1)
            set_publication(False)
            set_capture_message('')
            set_message('已按所列参数创建新运行；原运行已经保存。')
        except Exception as exc:
            set_message(f'配置未生效：{exc}')

    def next_step():
        playing.set(False)
        if mode == '实时实验':
            model.step()
            revision.set(revision.value+1)
        else:
            set_selected_index(min(index+1, len(steps)-1))

    def select_time(value):
        playing.set(False)
        set_selected_index(min(value, len(steps)-1))
        set_follow(False)

    def open_replay():
        try:
            replay = Trajectory(replay_path)
            replay.available_steps()
            playing.set(False)
            model.close()
            set_replay_directory(replay_path)
            set_mode('历史回放')
            set_follow(False)
            set_selected_index(0)
            set_exported('')
            set_pending({})
            set_selected_uid(-1)
            set_publication(False)
            set_capture_message('')
            set_message('历史回放只读取已有快照，不执行仿真。')
        except Exception as exc:
            set_message(f'无法读取轨迹：{exc}')

    def click_resident(event):
        points = event.get('points', {})
        if isinstance(points, dict) and points.get('xs') and points.get('ys'):
            x, y = round(points['xs'][0]), round(points['ys'][0])
        elif isinstance(points, list) and points:
            x, y = round(points[0]['x']), round(points[0]['y'])
        else:
            return
        set_selected_resident((x, y))

    def export():
        try:
            target = Path(directory) / 'figures' / f'step_{selected_step:06d}'
            result = export_publication(directory, target, display_config.get('figure_config', 'configs/figures.yaml'), selected_step)
            set_exported(str(result))
            set_message(f'已从保存的 step {selected_step} 记录导出图版与来源清单。')
        except Exception as exc:
            set_message(f'导出失败：{exc}')

    def save_capture(payload):
        from visualization.population import save_browser_capture
        try:
            file=save_browser_capture(trajectory,payload)
            set_capture_message(f'已保存实际场景截图：{file}')
        except Exception as exc:
            set_capture_message(f'截图保存失败：{exc}')

    solara.Title('群体动力学实验室')
    ResetSceneViewport(epoch=directory).key(directory)
    solara.Style(Path(__file__).with_name('theme.css').read_text(encoding='utf-8'))
    with solara.Sidebar():
        solara.Markdown('<div class="lab-sidebar-heading"><span class="eyebrow">EXPERIMENT CONTROLS</span><h1>观察个体，<br>理解群体。</h1><p>局部交互、真实主体与可追溯的演化过程。</p></div>')
        choices = {'鱼群与鲨鱼 · Collective Motion': 'configs/fish.yaml', '扩展 Schelling · 100×100': 'configs/schelling.yaml', '标准 Schelling · Mesa 3.5.2': 'configs/schelling_standard.yaml', 'Covasim · 原生2.0.0': 'configs/covasim.yaml'}
        selected_label = next((name for name,path in choices.items() if Path(path).resolve() == Path(config_path).resolve()), None)
        if selected_label is None:
            choices['自定义配置'] = config_path
            selected_label = '自定义配置'
        solara.Select('模型配置', values=list(choices), value=selected_label, on_value=lambda label: replace(choices[label]), disabled=playing.value)
        with solara.Details(summary='YAML 配置',expand=False):
            solara.InputText('YAML路径',value=loaded_path,on_value=set_loaded_path)
            solara.Button('加载 YAML',on_click=lambda:replace(loaded_path),disabled=playing.value)
        panel = actual_config
        read_only = mode == '历史回放'
        p = panel['parameters']
        def parameter(key, value):
            set_pending({**pending, key: value})
        solara.InputInt('随机种子', value=pending.get('seed',panel['seed']), on_value=lambda value: parameter('seed',value), disabled=read_only)
        if panel['model'].startswith('schelling'):
            solara.Markdown(f"**空间** {p['width']}×{p['height']}　**上限** {panel['steps']}轮  \n**邻域** Moore / r={p['radius']}　**边界** {'周期' if p['torus'] else '非周期'}")
            for key, label in [('density','初始占用概率'),('minority_pc','群体B初始概率')]:
                solara.InputFloat(label, value=pending.get(key,p[key]), on_value=lambda value,k=key: parameter(k,value), disabled=read_only)
            if panel['model'] == 'schelling_extended':
                for key,label in [('homophily_mean','偏好均值'),('homophily_std','偏好标准差')]:
                    solara.InputFloat(label,value=pending.get(key,p[key]),on_value=lambda value,k=key: parameter(k,value), disabled=read_only)
                solara.InputInt('迁居搜索半径',value=pending.get('relocation_radius',p['relocation_radius']),on_value=lambda value: parameter('relocation_radius',value), disabled=read_only)
                solara.Markdown(f"偏好截断区间 [{p['homophily_min']}, {p['homophily_max']}]  \n选择策略：局部优先满意，其次严格改善")
            else:
                solara.InputFloat('同类偏好阈值',value=pending.get('homophily',p['homophily']),on_value=lambda value: parameter('homophily',value), disabled=read_only)
        elif panel['model']=='fish':
            from simulations.fish.adapter import controls
            specs=controls()
            solara.InputText('搜索鱼群参数',value=parameter_search,on_value=set_parameter_search)
            groups={}
            for key,spec in specs.items():
                if parameter_search and parameter_search.lower() not in (key+spec['label']+spec['group']).lower():
                    continue
                groups.setdefault(spec['group'],[]).append((key,spec))
            for group,fields in groups.items():
                with solara.Details(summary=f'{group} · {len(fields):02d}',expand=bool(parameter_search) or group=='鱼的运动'):
                    for key,spec in fields:
                        parent,leaf=key.split('.')
                        value=pending.get(key,p[parent][leaf])
                        callback=lambda value,k=key:parameter(k,value)
                        if spec['type']=='int':
                            solara.InputInt(spec['label'],value=value,on_value=callback,disabled=read_only)
                        elif spec['type']=='float':
                            solara.InputFloat(spec['label'],value=value,on_value=callback,disabled=read_only)
                        else:
                            options=spec['options']
                            solara.Select(spec['label'],values=list(options.values()),value=options[value],
                                          on_value=lambda value,k=key,o=options:parameter(k,next(name for name,label in o.items() if label==value)),disabled=read_only)
        else:
            solara.Markdown(f"**人口** {p['pop_size']:,}　**日更新上限** {panel['steps']}  \n**人口模型** 原生 Hybrid　**历史校准** 未进行")
            solara.InputFloat('传播参数 beta',value=pending.get('beta',p['beta']),on_value=lambda value: parameter('beta',value), disabled=read_only)
            solara.InputInt('初始感染人数',value=pending.get('pop_infected',p['pop_infected']),on_value=lambda value: parameter('pop_infected',value), disabled=read_only)
        solara.Markdown('<div class="lab-caption">修改后点击“重置并应用”生效；实际参数会保存至本次运行的配置文件。</div>', unsafe_solara_execute=False)
        solara.Button('创建所选模型新运行' if read_only else '重置并应用',on_click=lambda: replace(config_path,pending),disabled=playing.value,color='#27776c')
        solara.Markdown('### 历史轨迹')
        solara.InputText('已有运行目录',value=replay_path,on_value=set_replay_path)
        solara.Button('打开历史回放',on_click=open_replay,disabled=playing.value)
        solara.Markdown('### Publication Mode')
        solara.Checkbox(label='显示论文图版',value=publication,on_value=set_publication)
        solara.Button('导出 SVG + PNG 300/600 DPI',on_click=export,disabled=playing.value)
        if exported:
            for name in ('publication.svg','publication_300dpi.png','publication_600dpi.png','figure_manifest.json'):
                file=Path(exported)/name
                if file.exists():
                    solara.FileDownload(data=lambda f=file: f.read_bytes(),filename=name,label=name)

    metadata = trajectory.metadata()
    title = {'schelling_extended':'居民偏好与局部迁居','schelling_standard':'标准居住隔离模型','schelling':'标准居住隔离模型','covasim':'城市传染病传播','fish':'从邻域交互到群体运动'}[actual_config['model']]
    status = metadata.get('status','running' if playing.value else 'paused')
    eyebrow={'fish':'LOCAL INTERACTIONS / FISH SCHOOL','covasim':'CONTACT NETWORKS / EPIDEMIC DYNAMICS'}.get(actual_config['model'],'LOCAL PREFERENCES / RESIDENTIAL DYNAMICS')
    solara.Markdown(f'<div class="lab-stage-heading"><div><span class="eyebrow">{eyebrow}</span><h2>{title}</h2></div><div class="lab-stage-badges"><span>{mode}</span><span>{status}</span></div></div>')
    solara.Markdown(f'<div class="lab-scene-meta">场景 {metadata["scenario_version"]}　·　step {selected_step} / 已记录 {steps[-1]}　·　随机种子 {actual_config["seed"]}</div>')
    def time_controls():
        with solara.Row():
            solara.Button('暂停' if playing.value else ('连续运行' if mode == '实时实验' else '播放轨迹'), on_click=lambda: playing.set(not playing.value), disabled=mode=='实时实验' and model.session.closed, color='#27776c')
            solara.Button('单步执行' if mode=='实时实验' else '下一已记录时点',on_click=next_step,disabled=playing.value or (mode=='实时实验' and model.session.closed))
            solara.Checkbox(label='跟随最新状态',value=follow,on_value=set_follow,disabled=mode=='历史回放')
        solara.SliderInt(f'已保存时间轴 · step {selected_step}',value=index,min=0,max=max(1,len(steps)-1),on_value=select_time,disabled=len(steps)<2)
    if actual_config['model'].startswith('schelling') or publication:
        time_controls()
    if message and actual_config['model'] != 'covasim':
        solara.Markdown(message)
    if publication:
        fig,_ = publication_figure(trajectory,settings,selected_step)
        solara.FigureMatplotlib(fig,format='png')
    elif actual_config['model']=='fish':
        from visualization.fish import FishScene,fish_packet,fish_display
        packet=fish_packet(trajectory,selected_step)
        FishScene(frame=packet,settings=fish_display(display_config.get('fish_config','configs/fish_display.yaml')),playing=playing.value,event_capture=save_capture)
        with solara.Column(classes=['lab-controls']):
            time_controls()
        if capture_message:
            solara.Markdown(capture_message)
        solara.Markdown(f'<div class="lab-status-strip"><div><span>鱼群个体</span><strong>{len(packet["agents"]):,}</strong></div><div><span>捕食者</span><strong>{len(packet["predators"]):,}</strong></div><div><span>仿真步数</span><strong>{selected_step}</strong></div><div><span>模型时间</span><strong>{packet["time"]:.2f} s</strong></div></div>')
    elif actual_config['model'].startswith('schelling'):
        with solara.Row():
            solara.Checkbox(label='叠加不满意居民',value=show_unhappy,on_value=set_show_unhappy)
            solara.Checkbox(label='局部同类邻居比例热力图',value=show_similarity,on_value=set_show_similarity)
        with solara.Row():
            with solara.Column(style='width:70%'):
                solara.FigurePlotly(interactive_grid(trajectory,selected_step,similarity=show_similarity,unhappy=show_unhappy,recent_steps=display_config.get('recent_steps',3)),on_click=click_resident)
            with solara.Column(style='width:30%'):
                solara.Markdown('### 初始空间')
                solara.FigurePlotly(interactive_grid(trajectory,steps[0],recent_steps=0,height=230))
                solara.Markdown('### 最新已保存空间')
                solara.FigurePlotly(interactive_grid(trajectory,steps[-1],recent_steps=0,height=230))
        if selected_resident:
            x,y=selected_resident
            states=trajectory.read_snapshot(selected_step)
            row=states.loc[(states.x==x)&(states.y==y)]
            if len(row):
                resident=row.iloc[0]
                recent=trajectory.read('events',end=selected_step,agent_id=int(resident.agent_id))
                moves=recent.loc[recent.moved]
                last=f"step {int(moves.iloc[-1].step)}" if len(moves) else '尚无搬迁记录'
                theta=resident.get('theta_i',actual_config['parameters'].get('homophily'))
                solara.Markdown(f"**居民 {int(resident.agent_id)}**　群体 {'A' if resident.kind==0 else 'B'}　·　位置 ({x},{y})　·　偏好阈值 {theta:.4f}　·　{'满意' if resident.happy else '不满意'}　·　最近迁居 {last}")
            else:
                solara.Markdown(f'位置 ({x},{y})：空置住房。')
        solara.FigurePlotly(interactive_schelling_curves(trajectory,selected_step))
    else:
        from visualization.population import population_layout, population_frame, PopulationScene, save_browser_capture, population_settings
        psettings = population_settings(display_config.get('population_config','configs/population.yaml'))
        try:
            layout = population_layout(str(Path(directory).resolve()),psettings['layout_seed'],psettings['layout_iterations'])
            frame = population_frame(trajectory,selected_step,selected_uid,psettings['recent_steps'])
            def capture(payload):
                try:
                    file=save_browser_capture(trajectory,payload)
                    set_capture_message(f'已保存真实浏览器画面：{file}')
                except Exception as exc:
                    set_capture_message(f'画面保存失败：{exc}')
            PopulationScene(frame=frame,scene_layout=layout,selected_uid=selected_uid,on_selected_uid=set_selected_uid,
                            height=psettings['height'],max_edges=psettings['max_edges'],pulse_ms=psettings['pulse_ms'],event_capture=capture)
        except (ValueError,FileNotFoundError) as exc:
            solara.Error(f'主体网络需要已记录的主体、接触和事件表：{exc}')
        with solara.Column(classes=['lab-controls']):
            time_controls()
        if capture_message:
            solara.Markdown(capture_message)
        if message:
            solara.Markdown(message)
        solara.Button('收起辅助分析' if analysis_open else '展开辅助分析',on_click=lambda: set_analysis_open(not analysis_open))
        if analysis_open:
            solara.Markdown('疾病状态曲线存在重叠；年龄图使用互斥状态。网络只展示已记录成功感染，不使用潜在接触边推造传播。')
            solara.SliderInt('传播网络时间窗口起点（已记录步）',value=min(window_start,selected_step),min=0,max=max(1,selected_step),on_value=set_window_start)
            views=interactive_covasim(trajectory,selected_step,settings,start=min(window_start,selected_step))
            with solara.Row():
                with solara.Column(style='width:55%'):
                    solara.FigurePlotly(views[0])
                with solara.Column(style='width:45%'):
                    solara.FigurePlotly(views[1])
            with solara.Row():
                with solara.Column(style='width:50%'):
                    solara.FigurePlotly(views[2])
                with solara.Column(style='width:50%'):
                    solara.FigurePlotly(views[3])
        solara.Markdown('### 公共卫生干预时间表')
        schedule = intervention_schedule(actual_config)
        for item_index,item in enumerate(actual_config['parameters']['interventions']):
            days = [s['native_day'] for s in schedule if s['configuration_index']==item_index]
            state='已到配置开始日' if selected_step-1>=min(days) else '尚未到配置开始日'
            details=[]
            for key,value in item.items():
                if key in ('type','start_day','days'):
                    continue
                shown = ', '.join(f'{LAYERS.get(k,k)}: {v}' for k,v in value.items()) if isinstance(value,dict) else str(value)
                details.append(f"{key.replace('_',' ')}: {shown}")
            solara.Markdown(f"**{INTERVENTIONS[item['type']]}**　原生日 {', '.join(map(str,days))}　·　{state}  \n"+'　·　'.join(details))
    solara.Markdown('<div class="lab-footer"><span>AGENT-BASED SIMULATION</span><p>所有状态来自实际仿真记录。镜头与显示不参与主体决策。</p></div>')
