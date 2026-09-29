#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 archbench 的运行结果整理成 Markdown 表格。

数据来源: archbench/result/*.log (由 scripts/run.sh 生成, 每跑一次覆盖一次)
输出位置: perf.md 里 <!-- archbench:start --> ... <!-- archbench:end --> 之间的表格区
          (archbench/ 本身被 .gitignore 忽略, 所以记录写进被跟踪的 perf.md)

用法:
    python3 archbench/scripts/record.py                 # 只打印表格, 不改文件
    python3 archbench/scripts/record.py -w              # 写入 perf.md (追加一格汇总 + 刷新明细)
    python3 archbench/scripts/record.py -w --note "支持 SimpleBus 的 IFU"
    python3 archbench/scripts/record.py -n 3            # 明细只列前 N 项(按 bench 名排序)
    python3 archbench/scripts/record.py -w -t other.md  # 换个目标文件
"""

import argparse
import math
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # archbench/
RESULT = ROOT / 'result'
BENCH = ROOT / 'bench'
REPO = ROOT.parent                                     # ysyx-workbench-cddaaaa/

MARK_START = '<!-- archbench:start -->'
MARK_END = '<!-- archbench:end -->'
DEFAULT_TARGET = REPO / 'perf.md'

ANSI = re.compile(r'\x1b\[[0-9;]*m')


def benchlist():
    """和 scripts/benchlist/all.sh 一致: bench/ 下除 000.hello 之外的所有项(按名字排序)"""
    if not BENCH.is_dir():
        return []
    return sorted(d.name for d in BENCH.iterdir() if d.is_dir() and d.name != '000.hello')


def parse_log(path):
    body = ANSI.sub('', path.read_text(errors='replace'))
    d = {'bench': path.stem}

    m = re.search(r'# Building \S+ \[(.+?)\]', body)
    d['arch'] = m.group(1) if m else '?'
    m = re.search(r'^mainargs=(.*)$', body, re.M)
    d['mainargs'] = m.group(1).strip() if m else ''

    m = re.search(r'\[RESULT\](.*)$', body, re.M)
    d['passed'] = bool(m) and 'PASS' in m.group(1)
    m = re.search(r'^\s*(\d+)\s+Marks\s*$', body, re.M)
    d['marks'] = int(m.group(1)) if m else None
    m = re.search(r'Scored time:\s*\S+\s*\((\d+) us\)', body)
    d['scored_us'] = int(m.group(1)) if m else None
    m = re.search(r'Total\s+time:\s*\S+\s*\((\d+) us\)', body)
    d['total_us'] = int(m.group(1)) if m else None
    m = re.search(r'\[WALL\]\s*([\d.]+)\s*s', body)
    d['wall_s'] = float(m.group(1)) if m else None
    m = re.search(r'Difftest PASS:\s*(\d+) instructions executed in (\d+) cycles', body)
    d['insts'] = int(m.group(1)) if m else None
    d['cycles'] = int(m.group(2)) if m else None
    d['ipc'] = (d['insts'] / d['cycles']) if (d.get('insts') and d.get('cycles')) else None

    if d['marks'] is not None:
        d['status'] = 'OK'
    elif d['wall_s'] is not None:
        d['status'] = '无结果'   # 跑完/超时了但没产出 [RESULT]
    else:
        d['status'] = '中断'
    return d


def collect():
    rows = []
    for name in benchlist():
        log = RESULT / (name + '.log')
        if log.exists():
            rows.append(parse_log(log))
        else:
            rows.append({'bench': name, 'arch': '?', 'mainargs': '', 'marks': None,
                         'status': '无日志', 'wall_s': None, 'insts': None,
                         'cycles': None, 'ipc': None, 'scored_us': None, 'total_us': None})
    return rows


def git_commit(override=None):
    """当前 HEAD 的短 hash。npc/ 有未提交改动时加 '*' 警示
    (否则会把"改了 RTL 但没提交就跑的评测"错记成 HEAD 那个版本)。"""
    if override:
        return override
    try:
        rev = subprocess.check_output(
            ['git', '-C', str(REPO), 'rev-parse', '--short', 'HEAD'],
            stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return '?'
    try:
        dirty = subprocess.check_output(
            ['git', '-C', str(REPO), 'status', '--porcelain', '--', 'npc'],
            stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        dirty = ''
    return rev + '*' if dirty else rev


def fmt(v, unit='', dash='—'):
    return dash if v is None else (f'{v}{unit}' if not isinstance(v, float) else f'{v:.2f}{unit}')


def detail_table(rows):
    out = ['| bench | Marks | Scored | Total | WALL | 指令数 | 周期数 | IPC | 备注 |',
           '|---|---:|---:|---:|---:|---:|---:|---:|---|']
    for r in rows:
        out.append('| {} | {} | {} | {} | {} | {} | {} | {} | {} |'.format(
            r['bench'],
            fmt(r['marks']),
            fmt(r['scored_us'], ' us'),
            fmt(r['total_us'], ' us'),
            fmt(r['wall_s'], ' s'),
            fmt(r['insts']),
            fmt(r['cycles']),
            fmt(r['ipc']),
            r['status'],
        ))
    return '\n'.join(out)


def existing_summary_rows(text):
    """取出标记区里已有的汇总数据行(不含表头/分隔线)"""
    if MARK_START not in text or MARK_END not in text:
        return []
    inner = text.split(MARK_START, 1)[1].split(MARK_END, 1)[0]
    rows, in_sum = [], False
    for line in inner.split('\n'):
        if line.startswith('### 汇总'):
            in_sum = True
            continue
        if line.startswith('###'):
            in_sum = False
            continue
        if in_sum and line.startswith('|'):
            if set(line) <= set('|-: '):        # 分隔线 |---|---|
                continue
            if '日期' in line:                  # 表头
                continue
            rows.append(line.rstrip())
    return rows


def build_content(rows, prev_rows, note, stamp, commit, arch, mainargs, n_detail):
    ok = [r['marks'] for r in rows if r['marks']]
    geomean = int(round(math.exp(sum(math.log(v) for v in ok) / len(ok)))) if ok else 0
    mean = int(sum(ok) / len(ok)) if ok else 0
    summary_row = ('| {} | {} | {} | {} | {}/{} | {} | {} | {} |'.format(
        stamp, commit, arch, mainargs or '—', len(ok), len(rows), geomean, mean, note or ''))

    head = rows[:n_detail] if n_detail > 0 else rows
    lines = [
        '### 汇总',
        '',
        '| 日期 | commit | ARCH | mainargs | 成功/总数 | GEOMEAN | MEAN | 备注 |',
        '|---|---|---|---|---:|---:|---:|---|',
        *prev_rows,
        summary_row,
        '',
        f'### 明细（最近一次: {stamp}）',
        '',
        detail_table(head),
        '',
        '> 在 `archbench/scripts` 下执行 `bash run.sh ARCH=... mainargs=train`，'
        '再 `python3 record.py -w` 更新上表。',
        '> `commit` 带 `*` 表示评测时 `npc/` 有未提交改动, 不代表 HEAD 那个版本。',
        '> GEOMEAN/MEAN 只对产出 `[RESULT]` 的项计算（`run.sh` 自己的 excel.txt '
        '在任一项为 0 时会把 GEOMEAN 算成 0）。',
        '',
    ]
    return '\n'.join(lines), geomean, mean, len(ok)


def splice(target, content):
    text = target.read_text(encoding='utf-8')
    if MARK_START in text and MARK_END in text:
        pre, rest = text.split(MARK_START, 1)
        _, post = rest.split(MARK_END, 1)
        target.write_text(pre + MARK_START + '\n' + content + MARK_END + post, encoding='utf-8')
    else:
        target.write_text(text.rstrip() + '\n\n' + MARK_START + '\n' + content + MARK_END + '\n',
                          encoding='utf-8')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-w', '--write', action='store_true', help='写入目标 Markdown')
    ap.add_argument('-t', '--target', default=str(DEFAULT_TARGET), help='目标 Markdown 文件')
    ap.add_argument('--note', default='', help='本次运行的备注(写进汇总表)')
    ap.add_argument('--commit', default=None, help='手动指定 commit 列(默认取 HEAD, 脏工作区会加 *)')
    ap.add_argument('-n', '--detail', type=int, default=0, help='明细只列前 N 项, 0 = 全部')
    args = ap.parse_args()

    rows = collect()
    if not rows:
        print('没找到 bench/, 请在 archbench/ 下运行', file=sys.stderr)
        return 1
    if not any(r['marks'] for r in rows):
        print('result/*.log 里没有任何 [RESULT], 先跑 bash run.sh ... 再说', file=sys.stderr)
        return 1

    arch = next((r['arch'] for r in rows if r['arch'] != '?'), '?')
    mainargs = next((r['mainargs'] for r in rows if r['mainargs']), '')
    stamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    commit = git_commit(args.commit)

    target = Path(args.target)
    prev = existing_summary_rows(target.read_text(encoding='utf-8')) if target.exists() else []
    content, geomean, mean, n_ok = build_content(
        rows, prev, args.note, stamp, commit, arch, mainargs, args.detail)
    print(content)

    if args.write:
        splice(target, content)
        print(f'\n[record] 已更新 {target}  (本次 GEOMEAN={geomean} MEAN={mean}, {n_ok}/{len(rows)} 项有结果)',
              file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
