"""Export original/executable/all-direction graph views without changing graphs."""
import argparse
from copy import deepcopy
import html
import json
from pathlib import Path
import shutil
import subprocess
import textwrap
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from matplotlib.patches import Rectangle, Patch
from PIL import Image, ImageOps

from .io import digest, read_json, save_json

STYLES = {'upward': ('#27667b', 'solid', 'Upward'),
          'downward': ('#b3653b', 'dashed', 'Downward'),
          'intra_scale': ('#6e648d', 'dotted', 'Same scale')}
SVG = 'http://www.w3.org/2000/svg'
ET.register_namespace('', SVG)
ET.register_namespace('xlink', 'http://www.w3.org/1999/xlink')


def _render_matplotlib(graph, base, path, title):
    """Use the SAME base positions/IDs for candidate and executable comparisons."""
    positions, labels = {}, {}
    by_scale = {s: [n for n in base['nodes'] if n['scale'] == s] for s in ('micro', 'meso', 'macro')}
    rows = max(2, max(map(len, by_scale.values())))
    for x, scale in enumerate(by_scale):
        nodes = by_scale[scale]
        for index, node in enumerate(nodes):
            positions[node['indicator_id']] = (float(x), 1.0 - index)
    for index, node in enumerate(base['nodes'], 1):
        labels[node['indicator_id']] = f'N{index}'
    with plt.rc_context({'font.family': ['Times New Roman', 'DejaVu Serif'], 'svg.fonttype': 'none'}):
        fig, ax = plt.subplots(figsize=(10, 6.5 + max(0, rows - 2) * 2.2))
        ax.set(xlim=(-.55, 2.55), ylim=(1.0 - rows, 1.75))
        ax.axis('off')
        boxes = {}
        for node in graph['nodes']:
            iid = node['indicator_id']; x, y = positions[iid]
            failed = any(r.get('status') == 'failed' for r in node.get('execution', {}).values())
            box = FancyBboxPatch((x - .37, y - .24), .74, .48, boxstyle='round,pad=0.018',
                                 facecolor='#f4f4f4' if failed else 'white', edgecolor='#444444',
                                 linewidth=1.2, linestyle='dashed' if failed else 'solid', zorder=3)
            box.set_gid('node_' + iid); ax.add_patch(box); boxes[iid] = box
            name = '\n'.join(textwrap.wrap(node['name'], width=24))
            suffix = '\n[not executable]' if failed else ''
            text = ax.text(x, y, labels[iid] + '\n' + name + suffix, ha='center', va='center',
                           fontsize=9.5, linespacing=1.12, zorder=4)
            text.set_gid('label_' + iid)
        for edge in graph['edges']:
            source, target = edge['source'], edge['target']
            a, b = positions[source], positions[target]
            rad = .34 if abs(a[0] - b[0]) > 1.5 and abs(a[1] - b[1]) < .1 else .16
            if a[0] == b[0]:rad = .23
            color, style, _ = STYLES[edge['scale_direction']]
            arrow = FancyArrowPatch(a, b, patchA=boxes[source], patchB=boxes[target],
                                    connectionstyle=f'arc3,rad={rad}', arrowstyle='-|>', mutation_scale=11,
                                    linewidth=1.0, linestyle=style, color=color, shrinkA=4, shrinkB=4, zorder=1)
            arrow.set_gid('edge_' + edge['edge_id']); ax.add_patch(arrow)
        for x, scale in enumerate(('Micro', 'Meso', 'Macro')):
            ax.text(x, 1.58, scale, ha='center', fontsize=12)
            if not any(n['scale'] == scale.lower() for n in graph['nodes']):
                ax.text(x, .48, 'No executable nodes' if 'executable' in title.lower() else 'No nodes',
                        ha='center', va='center', fontsize=9, color='#777777')
        ax.text(-.52, 1.7, title, fontsize=13, ha='left', va='top')
        ax.text(2.52, 1.7, f'{len(graph["nodes"])} nodes / {len(graph["edges"])} edges', fontsize=9, ha='right', va='top')
        for index, (direction, (color, style, label)) in enumerate(STYLES.items()):
            x = -.35 + index * 1.02
            ax.plot([x, x + .18], [1.32 - rows, 1.32 - rows], color=color, linestyle=style, linewidth=1.4)
            ax.text(x + .22, 1.32 - rows, label, va='center', fontsize=9)
        ax.text(1, 1.13 - rows, 'Unvalidated semantic hypotheses. Executability is not causal evidence.',
                ha='center', va='center', fontsize=8, color='#555555')
        fig.subplots_adjust(left=.02, right=.98, bottom=.02, top=.98)
        fig.savefig(path.with_suffix('.png'), dpi=180, facecolor='white')
        fig.savefig(path.with_suffix('.svg'), facecolor='white')
        plt.close(fig)
    _annotate_svg(graph, labels, path)


def _annotate_svg(graph, labels, path):
    tree = ET.parse(path.with_suffix('.svg'))
    for node in graph['nodes']:
        detail = (f"{labels[node['indicator_id']]} | {node['indicator_id']}\n{node['name']}\n"
                  f"Scale: {node['scale']} | Phenomenon: {node['phenomenon_id']}\n"
                  f"Definition: {node['mathematical_definition']}\nExecution: {node.get('execution', {})}")
        for prefix in ('node_', 'label_'):
            element = tree.find(f".//*[@id='{prefix + node['indicator_id']}']")
            if element is not None:
                for old in element.findall(f'{{{SVG}}}title'):
                    element.remove(old)
                ET.SubElement(element, f'{{{SVG}}}title').text = detail
                element.set('tabindex', '0'); element.set('class', 'inspectable')
                element.set('data-node-id', node['indicator_id'])
    for edge in graph['edges']:
        element = tree.find(f".//*[@id='edge_{edge['edge_id']}']")
        if element is not None:
            for old in element.findall(f'{{{SVG}}}title'):
                element.remove(old)
            ET.SubElement(element, f'{{{SVG}}}title').text = f"{edge['source']} → {edge['target']}\n{edge['scale_direction']}\n{edge['semantic_rationale']}"
            element.set('class', 'inspectable')
            element.set('data-source', edge['source']); element.set('data-target', edge['target'])
    tree.write(path.with_suffix('.svg'), encoding='utf-8', xml_declaration=True)


def _render_dot(graph, base, path, title, dot):
    """Ranked compact layout and routed splines; graph identities stay unchanged."""
    q = lambda value: json.dumps(str(value), ensure_ascii=False)
    labels = {n['indicator_id']: f'N{i}' for i, n in enumerate(base['nodes'], 1)}
    lines = ['digraph G {',
             'graph [rankdir=LR, newrank=true, nodesep=0.15, ranksep=0.42, splines=spline, '
             'outputorder=edgesfirst, pad=0.12, bgcolor="white", fontname="Times New Roman", '
             'fontsize=17, labelloc=t, labeljust=l, dpi=150];',
             'node [shape=box, style="rounded,filled", fillcolor="white", color="#444444", '
             'fontname="Times New Roman", fontsize=14, margin="0.10,0.07", penwidth=1.1];',
             'edge [arrowsize=0.7, penwidth=1.0];',
             'label=<<TABLE BORDER="0" CELLBORDER="0" CELLPADDING="2">'
             f'<TR><TD ALIGN="LEFT">{html.escape(title)}</TD></TR>'
             f'<TR><TD ALIGN="LEFT"><FONT POINT-SIZE="12">{len(graph["nodes"])} nodes / {len(graph["edges"])} edges</FONT></TD></TR>'
             '<TR><TD ALIGN="LEFT"><FONT POINT-SIZE="10" COLOR="#27667b">Upward: solid</FONT>'
             ' | <FONT POINT-SIZE="10" COLOR="#b3653b">Downward: dashed</FONT>'
             ' | <FONT POINT-SIZE="10" COLOR="#6e648d">Same scale: dotted</FONT></TD></TR></TABLE>>;']
    if not graph['nodes']:
        lines.append('empty [label="No nodes passed execution acceptance", shape=plaintext];')
    for scale in ('micro', 'meso', 'macro'):
        nodes = [n for n in graph['nodes'] if n['scale'] == scale]
        if not nodes:
            continue
        lines += [f'subgraph cluster_{scale} {{', 'rank=same;',
                  f'label={q(scale.capitalize())}; color="#dddddd"; margin=10; fontsize=16;']
        for node in nodes:
            iid = node['indicator_id']
            failed = any(r.get('status') == 'failed' for r in node.get('execution', {}).values())
            label = labels[iid] + '\n' + '\n'.join(textwrap.wrap(node['name'], width=28))
            if failed:
                label += '\n[not executable]'
            style = 'rounded,filled,dashed' if failed else 'rounded,filled'
            lines.append(f'{q(iid)} [id={q("node_" + iid)}, label={q(label)}, '
                         f'style={q(style)}, fillcolor={q("#f2f2f2" if failed else "white")}];')
        lines.append('}')
    for edge in graph['edges']:
        direction = edge['scale_direction']
        color, style, _ = STYLES[direction]
        lines.append(f'{q(edge["source"])} -> {q(edge["target"])} [id={q("edge_" + edge["edge_id"])}, '
                     f'color={q(color)}, style={q(style)}, constraint={str(direction == "upward").lower()}];')
    lines.append('}')
    path.with_suffix('.dot').write_text('\n'.join(lines), encoding='utf-8')
    for extension in ('svg', 'png', 'pdf'):
        subprocess.run([dot, '-T' + extension, str(path.with_suffix('.dot')), '-o', str(path.with_suffix('.' + extension))],
                       check=True, capture_output=True, timeout=180)
    _annotate_svg(graph, labels, path)


def render_graph(graph, base, path, title, layout='auto'):
    dot = shutil.which('dot')
    if layout == 'graphviz' and not dot:
        raise ValueError('Graphviz dot is unavailable; use --layout matplotlib or install Graphviz separately')
    if layout != 'matplotlib' and dot:
        _render_dot(graph, base, path, title, dot)
        return 'graphviz_dot'
    _render_matplotlib(graph, base, path, title)
    return 'matplotlib'


def render_matrix(graph, path, title):
    """One exact cell per directed edge, without crossings or hidden links."""
    ordered = sorted(enumerate(graph['nodes'], 1), key=lambda item: ('micro', 'meso', 'macro').index(item[1]['scale']))
    labels = {n['indicator_id']: f'N{i}' for i, n in enumerate(graph['nodes'], 1)}
    coordinates = {n['indicator_id']: i for i, (_, n) in enumerate(ordered)}
    size = max(8, len(ordered) * .25)
    with plt.rc_context({'font.family': ['Times New Roman', 'DejaVu Serif'], 'svg.fonttype': 'none'}):
        fig, ax = plt.subplots(figsize=(size, size))
        count = len(ordered)
        ax.set(xlim=(-.5, count - .5), ylim=(count - .5, -.5), aspect='equal',
               xlabel='Target variable', ylabel='Source variable', title=title)
        ids = [n['indicator_id'] for _, n in ordered]
        ax.set_xticks(np.arange(count), [labels[i] for i in ids], rotation=90, fontsize=10)
        ax.set_yticks(np.arange(count), [labels[i] for i in ids], fontsize=10)
        for iid, label in zip(ids, ax.get_yticklabels()):
            label.set_gid('node_' + iid)
        for iid, label in zip(ids, ax.get_xticklabels()):
            label.set_gid('label_' + iid)
        ax.set_facecolor('#f7f7f7')
        for edge in graph['edges']:
            row, column = coordinates[edge['source']], coordinates[edge['target']]
            cell = Rectangle((column - .44, row - .44), .88, .88, facecolor=STYLES[edge['scale_direction']][0], linewidth=0)
            cell.set_gid('edge_' + edge['edge_id']); ax.add_patch(cell)
        scales = [n['scale'] for _, n in ordered]
        for i in range(1, count):
            if scales[i] != scales[i - 1]:
                ax.axhline(i - .5, color='#666666', linewidth=.8)
                ax.axvline(i - .5, color='#666666', linewidth=.8)
        ax.legend(handles=[Patch(facecolor=color, label=label) for color, _, label in STYLES.values()],
                  loc='upper center', bbox_to_anchor=(.5, -.08), ncol=3, frameon=False, fontsize=12)
        fig.tight_layout()
        for extension in ('png', 'svg', 'pdf'):
            fig.savefig(path.with_suffix('.' + extension), dpi=150, facecolor='white', bbox_inches='tight')
        plt.close(fig)
    _annotate_svg(graph, labels, path)


def export_visualizations(experiments, output, layout='auto'):
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    views, panels = [], []
    for experiment in map(Path, experiments):
        base = read_json(experiment / 'candidate_graph.json')
        scene = read_json(experiment / 'experiment.json')['model_name']
        entries = [('candidate', base, experiment / 'candidate_graph.json'),
                   ('executable', read_json(experiment / 'executable_graph.json'), experiment / 'executable_graph.json')]
        for direction in STYLES:
            subset = deepcopy(base)
            subset['edges'] = [e for e in base['edges'] if e['scale_direction'] == direction]
            entries.append((direction, subset, experiment / 'candidate_graph.json'))
        for file in sorted(experiment.glob('per_run/*/executable_graph.json')):
            entries.append(('run_' + file.parent.name[:10], read_json(file), file))
        if len(base['nodes']) > 12:
            entries.append(('matrix', base, experiment / 'candidate_graph.json'))
            for index, pid in enumerate(dict.fromkeys(n['phenomenon_id'] for n in base['nodes']), 1):
                subset = deepcopy(base)
                subset['nodes'] = [n for n in base['nodes'] if n['phenomenon_id'] == pid]
                ids = {n['indicator_id'] for n in subset['nodes']}
                subset['edges'] = [e for e in base['edges'] if e['source'] in ids and e['target'] in ids]
                entries.append((f'phenomenon_{index}', subset, experiment / 'candidate_graph.json'))
        for kind, graph, source_file in entries:
            filename = f'{scene}_{kind}'
            title = scene.capitalize() + ' | ' + ('Candidate hypotheses' if kind == 'candidate' else 'Executable hypotheses' if kind == 'executable' else kind)
            if kind == 'matrix':
                render_matrix(graph, output / filename, scene.capitalize() + ' | Directed adjacency matrix')
                engine = 'adjacency_matrix'
            else:
                engine = render_graph(graph, base, output / filename, title, layout)
            views.append({'name': title, 'file': filename, 'nodes': len(graph['nodes']), 'edges': len(graph['edges']),
                          'node_ids': [n['indicator_id'] for n in graph['nodes']],
                          'edge_ids': [e['edge_id'] for e in graph['edges']],
                          'source_graph': str(source_file.resolve()), 'source_graph_sha256': digest(source_file),
                          'edge_filter': kind if kind in STYLES else 'induced_phenomenon' if kind.startswith('phenomenon_') else None,
                          'layout_engine': engine, 'node_font_points': 14 if engine == 'graphviz_dot' else 10 if engine == 'adjacency_matrix' else 9.5})
            if kind in ('candidate', 'executable'):panels.append(output / (filename + '.png'))
    images = [Image.open(p).convert('RGB') for p in panels]
    if images:
        w, h = 1800, 1300
        overview = Image.new('RGB', (2 * w, ((len(images) + 1) // 2) * h), 'white')
        for index, image in enumerate(images):
            panel = ImageOps.pad(image, (w, h), color='white')
            overview.paste(panel, ((index % 2) * w, (index // 2) * h))
        overview.save(output / 'overview.png')
    sections, options = [], []
    for index, view in enumerate(views):
        svg = (output / (view['file'] + '.svg')).read_text(encoding='utf-8')
        svg = svg[svg.index('<svg'):]
        sections.append(f'<section class="graph" data-view="{index}" style="display:{"block" if index == 0 else "none"}">{svg}</section>')
        options.append(f'<option value="{index}">{html.escape(view["name"])}</option>')
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>候选图与执行结果</title>
<style>body{margin:24px auto;max-width:1600px;padding:0 18px;font:16px system-ui;color:#252525;background:#fafafa}header{display:flex;gap:20px;align-items:center;flex-wrap:wrap}select,button{padding:8px;font:inherit}.graph{overflow:auto;max-height:82vh;background:white;border:1px solid #ddd}svg{display:block;height:auto;background:white}.inspectable{cursor:pointer}#details{white-space:pre-wrap;line-height:1.5;padding:16px;background:#eee;border-radius:6px;overflow-wrap:anywhere}p{color:#555}</style>
<header><h1>候选图与可执行图</h1><label>图视图 <select id="view">''' + ''.join(options) + '''</select></label></header>
<p>所有边均未经过统计因果验证。向上：蓝色实线；向下：橙色虚线；同层：紫色点线。灰色虚线框表示未通过执行验收。按现象分图只显示该现象内部关系，跨现象关系见完整图和方向分图。点击节点或边查看定义与理由。</p><p><button id="fit">适应窗口</button> <button id="actual">原始字号</button> <button id="reset">显示全部关系</button> <label>缩放 <input id="zoom" type="range" min="20" max="250" value="100"> <span id="percent">100%</span></label> <label><input id="focus" type="checkbox" checked>点击节点突出相邻关系</label></p>''' + ''.join(sections) + '''<div id="details">选择节点或边以查看详情。</div>
<script>const select=document.getElementById('view');const zoom=document.getElementById('zoom');
const resize=()=>{document.querySelectorAll('.graph svg').forEach(svg=>{const w=svg.viewBox.baseVal.width;svg.style.width=(w*Number(zoom.value)/100)+'px'});document.getElementById('percent').textContent=zoom.value+'%'};
zoom.oninput=resize;document.getElementById('actual').onclick=()=>{zoom.value=100;resize()};document.getElementById('fit').onclick=()=>{const svg=document.querySelector('.graph:not([style*="none"]) svg');zoom.value=Math.max(20,Math.min(250,Math.round(svg.parentElement.clientWidth/svg.viewBox.baseVal.width*100)));resize()};resize();
const reset=()=>document.querySelectorAll('.inspectable').forEach(e=>e.style.opacity='1');document.getElementById('reset').onclick=reset;document.getElementById('focus').onchange=reset;
select.onchange=()=>{document.querySelectorAll('.graph').forEach(s=>s.style.display=s.dataset.view===select.value?'block':'none');document.getElementById('details').textContent='选择节点或边以查看详情。'};
document.querySelectorAll('.inspectable').forEach(e=>{const show=()=>{document.getElementById('details').textContent=e.querySelector('title').textContent;
if(e.dataset.nodeId&&document.getElementById('focus').checked){const svg=e.closest('svg');const id=e.dataset.nodeId;const neighbors=new Set([id]);svg.querySelectorAll('[data-source]').forEach(edge=>{const active=edge.dataset.source===id||edge.dataset.target===id;edge.style.opacity=active?'1':'0.08';if(active){neighbors.add(edge.dataset.source);neighbors.add(edge.dataset.target)}});svg.querySelectorAll('[data-node-id]').forEach(node=>node.style.opacity=neighbors.has(node.dataset.nodeId)?'1':'0.15')}};e.addEventListener('click',show);e.addEventListener('keydown',v=>{if(v.key==='Enter')show()})});</script></html>'''
    (output / 'index.html').write_text(page, encoding='utf-8')
    save_json(output / 'visualization_manifest.json', {'views': views, 'graph_semantics_changed': False,
        'direction_encoding': {k: {'color': v[0], 'line_style': v[1]} for k, v in STYLES.items()}})
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', action='append', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--layout', choices=['auto', 'graphviz', 'matplotlib'], default='auto')
    args = parser.parse_args(argv)
    print(export_visualizations(args.experiment, args.output, args.layout))


if __name__ == '__main__':main()
