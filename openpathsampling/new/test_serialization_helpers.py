from serialization_helpers import *
import numpy as np
import pytest

def toy_uuid_maker(name):
    return int(hash(name))

def toy_uuid_encode(name):
    return "U(" + str(toy_uuid_maker(name)) + ")"

class MockUUIDObject(object):
    def __init__(self, name, normal_attr=None, obj_attr=None,
                 list_attr=None, dict_attr=None):
        self.name = name
        self.__uuid__ = int(hash(name))
        self.dict_attr = dict_attr
        self.list_attr = list_attr
        self.obj_attr = obj_attr
        self.normal_attr = normal_attr

    def to_dict(self):
        return {
            'name': self.name,
            'obj_attr': self.obj_attr,
            'list_attr': self.list_attr,
            'dict_attr': self.dict_attr,
            'normal_attr': self.normal_attr
        }

    @classmethod
    def from_dict(cls, dct):
        # set UUID after
        return cls(name=None, **dct)

def create_test_objects():
    obj_int = MockUUIDObject(name='int', normal_attr=5)
    obj_str = MockUUIDObject(name='str', normal_attr='foo')
    obj_np = MockUUIDObject(name='np', normal_attr=np.array([1.0, 2.0]))
    obj_obj = MockUUIDObject(name='obj', obj_attr=obj_int)
    obj_lst = MockUUIDObject(name='lst', list_attr=[obj_int, obj_str])
    obj_dct = MockUUIDObject(name='dct', dict_attr={'foo': obj_str,
                                                    obj_int: obj_np})
    obj_nest = MockUUIDObject(
        name='nest',
        dict_attr={'bar': [obj_str, {obj_int: [obj_np, obj_obj]}]}
    )
    obj_repeat = MockUUIDObject('rep', list_attr=[obj_int, [obj_int]])
    all_objects = {
        obj.name : obj
        for obj in [obj_int, obj_str, obj_np, obj_obj, obj_lst, obj_dct,
                    obj_nest, obj_repeat]
    }
    return all_objects

all_objects = create_test_objects()


@pytest.mark.parametrize('obj', list(all_objects.values()))
def test_has_uuid(obj):
    assert has_uuid(obj)

def test_has_uuid_no_uuid():
    assert not has_uuid(10)
    assert not has_uuid('foo')

@pytest.mark.parametrize('name,obj', list(all_objects.items()))
def test_get_uuid(name, obj):
    assert get_uuid(obj) == str(int(hash(name)))

def test_get_uuid_none():
    assert get_uuid(None) is None

@pytest.mark.parametrize('obj,included_objs', [
    (all_objects['int'], []),
    (all_objects['str'], []),
    (all_objects['np'], []),
    (all_objects['obj'], [all_objects['int']]),
    (all_objects['lst'], [all_objects['int'], all_objects['str']]),
    (all_objects['dct'], [all_objects['str'], all_objects['int'],
                          all_objects['np']]),
    (all_objects['nest'], [all_objects['str'], all_objects['int'],
                           all_objects['np'], all_objects['obj']]),
    (all_objects['rep'], [all_objects['int']])
])
def test_get_all_uuids(obj, included_objs):
    expected = {str(o.__uuid__): o for o in included_objs}
    expected.update({str(obj.__uuid__): obj})
    assert get_all_uuids(obj) == expected

@pytest.mark.parametrize('obj,included_objs', [
    (all_objects['int'], []),
    (all_objects['str'], []),
    (all_objects['np'], []),
    (all_objects['obj'], []),
    (all_objects['lst'], [all_objects['str']]),
    (all_objects['dct'], [all_objects['str'], all_objects['np']]),
    (all_objects['nest'], [all_objects['str'], all_objects['np'],
                           all_objects['obj']]),
    (all_objects['rep'], [])
])
def test_get_all_uuids_with_known(obj, included_objs):
    expected = {str(o.__uuid__): o for o in included_objs}
    known_obj = all_objects['int']
    known_uuids = {str(known_obj.__uuid__): known_obj}
    if obj is not all_objects['int']:
        expected.update({str(obj.__uuid__): obj})
    assert get_all_uuids(obj, known_uuids=known_uuids) == expected

@pytest.mark.parametrize('obj,replace_dct', [
    (all_objects['int'], {'name': 'int', 'normal_attr': 5}),
    (all_objects['str'], {'name': 'str', 'normal_attr': 'foo'}),
    (all_objects['obj'], {'name': 'obj',
                          'obj_attr': toy_uuid_encode('int')}),
    (all_objects['lst'], {'name': 'lst',
                          'list_attr': [toy_uuid_encode('int'),
                                        toy_uuid_encode('str')]}),
    (all_objects['dct'], {'name': 'dct',
                          'dict_attr': {
                              'foo': toy_uuid_encode('str'),
                              toy_uuid_encode('int'): toy_uuid_encode('np')
                          }}),
    (all_objects['nest'], {
        'name': 'nest',
        'dict_attr': {
            'bar': [toy_uuid_encode('str'),
                    {toy_uuid_encode('int'): [toy_uuid_encode('np'),
                                              toy_uuid_encode('obj')]}]
        }}),
    (all_objects['rep'], {'name': 'rep',
                          'list_attr': [toy_uuid_encode('int'),
                                        [toy_uuid_encode('int')]]})
])
def test_replace_uuid(obj, replace_dct):
    after_replacement = {key: None
                         for key in ['name', 'dict_attr', 'list_attr',
                                     'normal_attr', 'obj_attr']}
    after_replacement.update(replace_dct)
    encoding = lambda x: "U(" + str(x) + ")"
    assert replace_uuid(obj.to_dict(), encoding) == after_replacement

def test_replace_uuid_ndarray():
    # can't use assert == with arrays
    after_replacement = {'name': 'np', 'dict_attr': None,
                         'list_attr': None, 'obj_attr': None,
                         'normal_attr': np.array([1.0, 2.0])}
    encoding = lambda x: "U(" + str(x) + ")"
    result = replace_uuid(all_objects['np'].to_dict(), encoding)
    assert set(result.keys()) == set(after_replacement.keys())
    for key in after_replacement:
        if key == 'normal_attr':
            assert np.allclose(result[key], after_replacement[key])
        else:
            assert result[key] == after_replacement[key]

@pytest.fixture
def cache_list():
    make_cache = lambda keys: {get_uuid(all_objects[key]): all_objects[key]
                               for key in keys}
    cache_1 = make_cache(['int', 'str'])
    cache_2 = make_cache(['obj'])
    return [cache_1, cache_2]

def test_search_caches(cache_list):
    for key in ['int', 'str', 'obj']:
        uuid = get_uuid(all_objects[key])
        assert search_caches(uuid, cache_list) == all_objects[key]
    # seearch in a single cache (listify)
    for key in ['int', 'str']:
        uuid = get_uuid(all_objects[key])
        assert search_caches(uuid, cache_list[0]) == all_objects[key]

def test_search_caches_missing(cache_list):
    assert search_caches("foo", cache_list, raise_error=False) is None
    uuid = get_uuid(all_objects['obj'])
    assert search_caches(uuid, cache_list[0], raise_error=False) is None

def test_seach_caches_missing_error(cache_list):
    with pytest.raises(KeyError):
        search_caches("foo", cache_list)

    with pytest.raises(KeyError):
        uuid = get_uuid(all_objects['obj'])
        search_caches(uuid, cache_list[0])

def test_from_dict_with_uuids(cache_list):
    # this one only uses lst
    pytest.skip()


