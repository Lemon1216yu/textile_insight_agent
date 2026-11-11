"""产物写入工具：覆盖前必须存档，且存档名不能互相顶掉（评审 F5）。"""
import json

from scripts.artifact_io import write_json


def _read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def test_write_json_archives_previous_result(tmp_path):
    target = tmp_path / 'evaluation-expanded.json'
    target.write_text(json.dumps({'count': 1}), encoding='utf-8')
    archived = write_json({'count': 52}, target)
    assert _read(target) == {'count': 52}
    assert archived is not None and _read(archived) == {'count': 1}
    assert archived.name.startswith('evaluation-expanded-prev-')


def test_write_json_without_previous_result_creates_no_backup(tmp_path):
    target = tmp_path / 'fresh.json'
    assert write_json({'count': 2}, target) is None
    assert _read(target) == {'count': 2}
    assert list(tmp_path.glob('*-prev-*')) == []


def test_consecutive_overwrites_in_same_second_do_not_clobber(tmp_path):
    """同一秒内连续覆盖两次，两份基线都必须留存（秒级时间戳会静默丢一份）。"""
    target = tmp_path / 'evaluation-expanded.json'
    target.write_text(json.dumps({'generation': 1}), encoding='utf-8')
    first = write_json({'generation': 2}, target)
    second = write_json({'generation': 3}, target)
    assert first != second
    assert sorted([_read(first)['generation'], _read(second)['generation']]) == [1, 2]
    assert _read(target)['generation'] == 3


def test_nested_directory_is_created(tmp_path):
    """多级目录必须自动创建（原实现对多级目录报 FileNotFoundError）。"""
    target = tmp_path / 'a' / 'b' / 'result.json'
    write_json({'ok': True}, target)
    assert _read(target) == {'ok': True}
