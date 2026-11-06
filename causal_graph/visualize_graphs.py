"""Export original/executable/all-direction graph views without changing graphs."""
import argparse
from copy import deepcopy
import html
from pathlib import Path
import textwrap
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from PIL import Image

from .io import digest, read_json, save_json

STYLES = {'upward': ('#27667b', 'solid', 'Upward'),
          'downward': ('#b3653b', 'dashed', 'Downward'),
          'intra_scale': ('#6e648d', 'dotted', 'Same scale')}
SVG = 'http://www.w3.org/2000/svg'
ET.register_namespace('', SVG)
ET.register_namespace('xlink', 'http://www.w3.org/1999/xlink')


def render_graph(graph, base, path, title):
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
    tree = ET.parse(path.with_suffix('.svg'))
    for node in graph['nodes']:
        detail = (f"{labels[node['indicator_id']]} | {node['indicator_id']}\n{node['name']}\n"
                  f"Scale: {node['scale']} | Phenomenon: {node['phenomenon_id']}\n"
                  f"Definition: {node['mathematical_definition']}\nExecution: {node.get('execution', {})}")
        for prefix in ('node_', 'label_'):
            element = tree.find(f".//*[@id='{prefix + node['indicator_id']}']")
            if element is not None:
                ET.SubElement(element, f'{{{SVG}}}title').text = detail
                element.set('tabindex', '0'); element.set('class', 'inspectable')
    for edge in graph['edges']:
        element = tree.find(f".//*[@id='edge_{edge['edge_id']}']")
        if element is not None:
            ET.SubElement(element, f'{{{SVG}}}title').text = f"{edge['source']} → {edge['target']}\n{edge['scale_direction']}\n{edge['semantic_rationale']}"
            element.set('class', 'inspectable')
    tree.write(path.with_suffix('.svg'), encoding='utf-8', xml_declaration=True)


def export_visualizations(experiments, output):
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
        for kind, graph, source_file in entries:
            filename = f'{scene}_{kind}'
            title = scene.capitalize() + ' | ' + ('Candidate hypotheses' if kind == 'candidate' else 'Executable hypotheses' if kind == 'executable' else kind)
            render_graph(graph, base, output / filename, title)
            views.append({'name': title, 'file': filename, 'nodes': len(graph['nodes']), 'edges': len(graph['edges']),
                          'node_ids': [n['indicator_id'] for n in graph['nodes']],
                          'edge_ids': [e['edge_id'] for e in graph['edges']],
                          'source_graph': str(source_file.resolve()), 'source_graph_sha256': digest(source_file),
                          'edge_filter': kind if kind in STYLES else None})
            if kind in ('candidate', 'executable'):panels.append(output / (filename + '.png'))
    images = [Image.open(p).convert('RGB') for p in panels]
    if images:
        w, h = images[0].size
        overview = Image.new('RGB', (2 * w, ((len(images) + 1) // 2) * h), 'white')
        for index, image in enumerate(images):overview.paste(image, ((index % 2) * w, (index // 2) * h))
        overview.save(output / 'overview.png')
    sections, options = [], []
    for index, view in enumerate(views):
        svg = (output / (view['file'] + '.svg')).read_text(encoding='utf-8')
        svg = svg[svg.index('<svg'):]
        sections.append(f'<section class="graph" data-view="{index}" style="display:{"block" if index == 0 else "none"}">{svg}</section>')
        options.append(f'<option value="{index}">{html.escape(view["name"])}</option>')
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>候选图与执行结果</title>
<style>body{margin:24px auto;max-width:1200px;padding:0 18px;font:16px system-ui;color:#252525;background:#fafafa}header{display:flex;gap:20px;align-items:center;flex-wrap:wrap}select{padding:8px;font:inherit}svg{width:100%;height:auto;background:white}.inspectable{cursor:pointer}#details{white-space:pre-wrap;line-height:1.5;padding:16px;background:#eee;border-radius:6px;overflow-wrap:anywhere}p{color:#555}</style>
<header><h1>候选图与可执行图</h1><label>图视图 <select id="view">''' + ''.join(options) + '''</select></label></header>
<p>所有边均未经过统计因果验证。虚线边框节点未通过本次执行验收；点击节点或边查看原始定义与理由。</p>''' + ''.join(sections) + '''<div id="details">选择节点或边以查看详情。</div>
<script>const select=document.getElementById('view');select.onchange=()=>{document.querySelectorAll('.graph').forEach(s=>s.style.display=s.dataset.view===select.value?'block':'none');document.getElementById('details').textContent='选择节点或边以查看详情。'};
document.querySelectorAll('.inspectable').forEach(e=>{const show=()=>{document.getElementById('details').textContent=e.querySelector('title').textContent};e.addEventListener('click',show);e.addEventListener('keydown',v=>{if(v.key==='Enter')show()})});</script></html>'''
    (output / 'index.html').write_text(page, encoding='utf-8')
    save_json(output / 'visualization_manifest.json', {'views': views, 'graph_semantics_changed': False,
        'direction_encoding': {k: {'color': v[0], 'line_style': v[1]} for k, v in STYLES.items()}})
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', action='append', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    print(export_visualizations(args.experiment, args.output))


if __name__ == '__main__':main()
