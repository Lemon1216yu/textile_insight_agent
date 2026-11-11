"""评测产物写入：覆盖前必须存档上一次结果（防止基线证据被静默覆盖）。"""
import json

from scripts.evaluate_expanded import write_report


def test_write_report_archives_previous_result(tmp_path):
    target = tmp_path / 'evaluation-expanded.json'
    target.write_text(json.dumps({'count': 1, 'passed': 1}), encoding='utf-8')
    write_report({'count': 52, 'passed': 49}, target)
    assert json.loads(target.read_text(encoding='utf-8'))['count'] == 52
    backups = list(tmp_path.glob('evaluation-expanded-prev-*.json'))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding='utf-8'))['count'] == 1


def test_write_report_without_previous_result_creates_no_backup(tmp_path):
    target = tmp_path / 'evaluation-expanded.json'
    write_report({'count': 2}, target)
    assert json.loads(target.read_text(encoding='utf-8'))['count'] == 2
    assert list(tmp_path.glob('*-prev-*.json')) == []
