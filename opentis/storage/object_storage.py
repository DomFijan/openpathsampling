import copy
import yaml
import types

import numpy as np
import opentis as paths
import simtk.unit as u

class ObjectStore(object):
    """
    Base Class for storing complex objects in a netCDF4 file. It holds a
    reference to the store file.
    """

    def __init__(self, storage, content_class, is_named=False, json=True,
                 dimension_units=None, enable_caching=True, load_partial=False,
                 nestable=False):
        """

        Parameters
        ----------
        storage
        content_class
        is_named
        json
        dimension_units
        enable_caching : bool
            if this is set to `True` caching is used to quickly access previously
            loaded objects (default)
        load_partial : bool
            if this is set to `True` the storage allows support for partial
            delayed loading of member variables. This is useful for larger
            objects that might only be required in particular circumstances.
            (default is `False`)
        nestable : bool
            if true this marks the content_class to be saved as nested dict
            objects and not a pointing to saved objects. So the saved complex
            object is only stored once and not split into several objects that
            are referenced by each other in a tree-like fashion


        Attributes
        ----------

        storage : Storage
            the reference the Storage object where all data is stored
        content_class : class
            a reference to the class type to be stored using this Storage
        is_named : bool
            if `True` objects can also be loaded by a string identifier/name
        json : string
            if already computed a JSON Serialized string of the object
        dimension_units : dict of {str : simtk.unit.Unit } or None
            representing a dict of string representing a dimension
            ('length', 'velocity', 'energy') pointing to
            the simtk.unit.Unit to be used. If not None overrides the standard
            units used in the storage
        simplifier : util.StorableObjectJSON
            an instance of a JSON Serializer
        identifier : str
            name of the netCDF variable that contains the string to be
            identified by. So far this is `name`
        cache : dict (int or str : object)
            a dictionary that holds references to all stored elements by index
            or string for named objects. This is only used for cached access
            is enable_caching is True (default)

        Notes
        -----
        The class that takes care of storing data in a file is called a Storage,
        so the netCDF subclassed Storage is a storage. The classes that know how
        to load and save an object from the storage are called stores,
        like ObjectStore, SampleStore, etc...

        """
        self.storage = storage
        self.content_class = content_class
        self.idx_dimension = content_class.__name__.lower()
        self.db = content_class.__name__.lower()
        self.cache = dict()
        self.is_named = is_named
        self.json = json
        self.simplifier = paths.storage.StorableObjectJSON(storage)
        self.identifier = self.db + '_name'

        if dimension_units is not None:
            self.dimension_units = dimension_units
        else:
            self.dimension_units = {}

        # First, apply standard decorator for loading and saving
        # this handles all the setting and getting of .idx and is
        # always necessary!

        _save = self.save
        self.save = types.MethodType(saveidx(_save), self)

        _load = self.load
        self.load = types.MethodType(loadidx(_load), self)

        if load_partial:
            # this allows the class to load members only if needed
            # adds a different __getattr__ to the content class
            # makes only sense if not already lazy loading
            # it uses load_constructor instead to create an empty object
            # and then each class can attach delayed loaders to load
            # when necessary, fall back is of course the normal load function

            if  hasattr(self, 'load_empty'):
                cls = self.content_class

                def _getattr(self, item):
                    if item == '_idx':
                        return self.__dict__['idx']

                    if hasattr(cls, '_delayed_loading'):
                        if item in cls._delayed_loading:
                            if self.__dict__[item] is None:
                                _loader = cls._delayed_loading['item']
                                _loader(self)

                    return self.__dict__[item]

                setattr(cls, '__getattr__', _getattr)

                _load = self.load
                self.load = types.MethodType(loadpartial(_load), self)

        if enable_caching:
            # wrap load/save to make this work. I use MethodType here to bind the
            # wrapped function to this instance. An alternative would be to
            # add the wrapper to the class itself, which would mean that all
            # instances have the same setting and a change would be present in all
            # instances. E.g., first instance has caching and the second not
            # when the second instance is created the change in the class would
            # also disable caching in the first instance. The present way with
            # bound methods is more flexible
            # Should be not really important, since there will be mostly only one
            # storage, but this way it is cleaner

            _save = self.save
            self.save = types.MethodType(savecache(_save), self)

            _load = self.load
            self.load = types.MethodType(loadcache(_load), self)

        self._register_with_storage(nestable=nestable)

    def __str__(self):
        return repr(self)

    def __repr__(self):
        return "%s(content_class=%s, variable_prefix=%s)" % (
            self.__class__.__name__, self.content_class, self.db)


    def idx(self, obj):
        """
        Return the index in this store for a given object

        Parameters
        ----------
        obj : object
            the object that can be stored in this store for which its index is
            to be returned

        Returns
        -------
        int or None
            The integer index of the given object or None if it is not stored yet
        """
        if hasattr(obj, 'idx'):
            if self in obj.idx:
                return obj.idx[self]

        return None

    @property
    def units(self):
        """
        Return the units dictionary used in the attached storage

        Returns
        -------
        units : dict of {str : simtk.unit.Unit }
            representing a dict of string representing a dimension
            ('length', 'velocity', 'energy')
            pointing to the simtk.unit.Unit to be used

        """
        return self.storage.units

    def _register_with_storage(self, nestable = False):
        """
        Register the store with the associated storage. This means the

        Parameters
        ----------
        nestable : bool
            if true this marks the content_class to be saved as nested dict
            objects and not a pointing to saved objects. So the saved complex
            object is only stored once and not split into several objects that
            are referenced by each other in a tree-like fashion

        Notes
        -----
        """

        self.storage._storages[self.content_class] = self
        self.storage._storages[self.content_class.__name__] = self
        self.storage._storages[self.content_class.__name__.lower()] = self

        # Add here the logic to change the actual class and add the decorator
        # this is the same as add the  decorator (without default_storage,
        # I removed this since it is not used anyway)
        # all it does is make sure that there is a .idx property and the base_
        # cls is known
        self.content_class.base_cls_name = self.content_class.__name__
        self.content_class.base_cls = self.content_class

        # add a property idx that keeps the storage reference

        def _idx(this):
            if not hasattr(this, '_idx'):
                this._idx = dict()

            return this._idx

        def _save(this, storage):
            storage.save(this)

        if nestable:
            self.content_class.nestable = True

        self.content_class.save = _save
        self.content_class.idx = property(_idx)

        # register as a base_class for storable objects
        self.storage.links.append(self)


    def set_variable_partial_loading(self, variable, loader):
        cls = self.content_class
        if not hasattr(cls, '_delayed_loading'):
            cls._delayed_loading = dict()

        cls._delayed_loading[variable] = loader

    def copy(self):
        """
        Create a deep copy of the ObjectStore instance

        Returns
        -------
        ObjectStore()
            the copied instance
        """
        store = copy.deepcopy(self)
        return store

    def __call__(self, storage):
        """
        Create a deep copy of the ObjectStore instance using the new store
        provided as function argument

        Returns
        -------
        ObjectStore()
            the copied instance
        """
        store = self.copy()
        store.storage = storage
        return store

    def idx_by_name(self, needle):
        """
        Return the index for the (first) object with a given name from the store

        Parameters
        ----------
        needle : str
            The name of the object to be found in the storage

        Returns
        -------
        int or None
            The index of the first found object. If the name is not present,
            None is returned

        Notes
        -----
        Can only be applied to named storages.
        """
        if self.is_named:
            # if we need a cache we might find the index in there
            if needle in self.cache:
                if type(self.cache[needle]) is int:
                    return self.cache[needle]
                else:
                    return self.cache[needle].idx[self.storage]

            # otherwise search the storage for the name
            found_idx = [ idx for idx,s in enumerate(self.storage.variables[
                self.identifier][:]) if s == needle
            ]

            if len(found_idx) > 0:
                    return found_idx[0]

            return None
        else:
            raise ValueError('Cannot search for name (str) in non-named objects')

    def update_name_cache(self):
        """
        Update the internal cache with all stored names in the store.
        This allows to load by name for named objects
        """
        if self.is_named:
            for idx, name in enumerate(self.variables[self.db + "_name"][:]):
                self.cache[name] = idx

    def iterator(this, iter_range = None):
        """
        Return an iterator over all objects in the storage

        Parameters
        ----------
        iter_range : slice or None
            if this is not `None` it confines the iterator to objects specified
            in the slice

        Returns
        -------
        Iterator()
            The iterator that iterates the objects in the store

        """
        class ObjectIterator:
            def __init__(self):
                self.storage = this
                self.iter_range = iter_range
                if iter_range is None:
                    self.idx = 0
                    self.end = self.storage.count()
                else:
                    self.idx = iter_range.start
                    self.end = iter_range.stop

            def __iter__(self):
                return self

            def next(self):
                if self.idx < self.storage.count():
                    obj = self.storage.load(self.idx)
                    if self.iter_range.step is not None:
                        self.idx += self.iter_range.step
                    else:
                        self.idx += 1
                    return obj
                else:
                    raise StopIteration()

        return ObjectIterator()

    def __getitem__(self, item):
        try:
            return self.load(item)
        except KeyError:
            return None

    def load(self, idx, lazy=False):
        '''
        Returns an object from the storage. Needs to be implemented from
        the specific storage class.

        Parameter
        ---------
        idx : int or str
            either the integer index of the object to be loaded or a string
            (name) for named objects. This will always return the first object
            found with the specified name.

        Returns
        -------
        object
            the loaded object
        '''

        return self.load_object(self.idx_dimension + '_json', idx)

    def save(self, obj, idx=None):
        """
        Saves an object the storage.

        Parameters
        ----------
        obj : object
            the object to be stored
        idx : int or string or `None`
            the index to be used for storing. This is highly discouraged since
            it changes an immutable object (at least in the storage). It is
            better to store also the new object and just ignore the
            previously stored one.

        """

        if self.is_named and hasattr(obj, 'name'):
            self.storage.variables[self.identifier][idx] = obj.name

        self.save_object(self.idx_dimension + '_json', idx, obj)

    def get_name(self, idx):
        """
        Return the name of and object with given integer index

        Parameters
        ----------
        idx : int
            the integer index of the object whose name is to be returned

        Returns
        -------
        str or None
            Returns the name of the object for named objects. None otherwise.

        """
        if self.is_named:
            return self.storage.variables[self.identifier][idx]
        else:
            return None

    def get(self, indices):
        """
        Returns a list of objects from the given list of indices

        Arguments
        ---------
        indices : list of int
            the list of integers specifying the object to be returned

        Returns
        -------
        list of objects
            a list of objects stored under the given indices

        """
        return [self.load(idx) for idx in range(0, self.count())[indices]]

    def last(self):
        '''
        Returns the last generated trajectory. Useful to continue a run.

        Returns
        -------
        Trajectoy
            the actual trajectory object
        '''
        return self.load(self.count())

    def first(self):
        '''
        Returns the last stored object. Useful to continue a run.

        Returns
        -------
        Object
            the actual last stored object
        '''
        return self.load(0)

    def count(self):
        '''
        Return the number of objects in the storage

        Returns
        -------
        number : int
            number of objects in the storage.
        '''
        return int(len(self.storage.dimensions[self.idx_dimension]))

    def free(self):
        '''
        Return the number of the next free index

        Returns
        -------
        index : int
            the number of the next free index in the storage. Used to store a new object.
        '''
        return self.count()

    def _init(self, units=None):
        """
        Initialize the associated storage to allow for object storage. Mainly creates an index dimension with the name of the object.

        Parameters
        ----------
        units : dict of {str : simtk.unit.Unit} or None
            representing a dict of string representing a dimension
            ('length', 'velocity', 'energy') pointing to
            the simtk.unit.Unit to be used. If not None overrides the standard
            units used in the storage
        """
        # define dimensions used for the specific object
        self.storage.createDimension(self.idx_dimension, 0)
        if self.is_named:
            self.init_variable(self.db + "_name", 'str', description='A short descriptive name for convenience', chunksizes=tuple([10240]))
        if self.json:
            self.init_variable(self.db + "_json", 'str', description='A json serialized version of the object', chunksizes=tuple([10240]))

#=============================================================================================
# INITIALISATION UTILITY FUNCTIONS
#=============================================================================================

    def init_dimension(self, name, length = 0):
        if name not in self.storage.dimensions:
            self.storage.createDimension(name, length)

        self.storage.sync()

    def init_mixed(self, name):
        # entry position is given by a start and a length
        self.init_variable(name + '_dim_begin', 'index', name)
        self.init_variable(name + '_dim_length', 'length', name)

        self.storage.sync()

    def init_variable(self, name, var_type, dimensions = None, units=None, description=None, variable_length=False, chunksizes=None):
        '''
        Create a new variable in the netcdf storage. This is just a helper function to structure the code better.

        Paramters
        =========
        name : str
            The name of the variable to be created
        var_type : str
            The string representing the type of the data stored in the variable.
            Either the netcdf types can be used directly and
            strings representing the python native types are translated to appropriate netcdf types.
        dimensions : str or tuple of str
            A tuple representing the dimensions used for the netcdf variable.
            If not specified then the default dimension of the storage is used.
        units : str
            A string representing the units used if the var_type is `float` the units is set to `none`
        description : str
            A string describing the variable in a readable form.
        variable_length : bool
            If true the variable is treated as a variable length (list) of the given type. A built-in example
            for this type is a string which is a variable length of char. This make using all the
            mixed stuff superfluous
        '''

        ncfile = self.storage


        if dimensions is None:
            dimensions = self.db

        nc_type = var_type
        if var_type == 'float':
            nc_type = np.float32   # 32-bit float
        elif var_type == 'int':
            nc_type = np.int32   # 32-bit signed integer
        elif var_type == 'index':
            nc_type = np.int32   # 32-bit signed integer / for indices / -1 indicates no index (None)
        elif var_type == 'length':
            nc_type = np.int32   # 32-bit signed integer / for indices / -1 indicated no length specified (None)
        elif var_type == 'bool':
            nc_type = np.uint8   # 8-bit signed integer for boolean
        elif var_type == 'str':
            nc_type = 'str'

        if variable_length:
            vlen_t = ncfile.createVLType(nc_type, name + '_vlen')
            ncvar = ncfile.createVariable(name, vlen_t, dimensions, zlib=False, chunksizes=chunksizes)
        else:
            ncvar = ncfile.createVariable(name, nc_type, dimensions, zlib=False, chunksizes=chunksizes)

        if var_type == 'float' or units is not None:

            unit_instance = u.Unit({})
            symbol = 'none'

            if isinstance(units, u.Unit):
                unit_instance = units
                symbol = unit_instance.get_symbol()
            elif isinstance(units, u.BaseUnit):
                unit_instance = u.Unit({units : 1.0})
                symbol = unit_instance.get_symbol()
            elif type(units) is str and hasattr(u, units):
                unit_instance = getattr(u, units)
                symbol = unit_instance.get_symbol()
            elif type(units) is str and units is not None:
                symbol = units

            json_unit = self.simplifier.unit_to_json(unit_instance)

            # store the unit in the dict inside the Storage object for fast access
            self.storage.units[name] = unit_instance

            # Define units for a float variable
            setattr(ncvar,      'unit_simtk', json_unit)
            setattr(ncvar,      'unit', symbol)

        if description is not None:
            # Define long (human-readable) names for variables.
            setattr(ncvar,    "long_str", description)

        self.storage.sync()


    def init_objectdict(self, name, obj_cls, value_type):
        self.init_dimension(name)

        self.init_variable(name + '_value', value_type, (name, obj_cls))
        self.init_variable(name + '_idx', 'index', (name, obj_cls))
        self.init_variable(name + '_length', 'length', (name))

#=============================================================================================
# LOAD / SAVE UTILITY FUNCTIONS
#=============================================================================================

    def load_variable(self, name, idx):
        return self.storage.variables[name][idx]

    def save_variable(self, name, idx, value):
        self.storage.variables[name][idx] = value

    def load_objectdict(self, name, idx, key_type, value_type):
        length = self.storage.variables[name + '_length'][idx]
        values = self.get_list_as_type(name + '_value', idx, 0, length, value_type)
        keys = self.get_list_as_type(name + '_idx', idx, 0, length, key_type)

        data = dict(zip(keys, values))
        return data

    def save_objectdict(self, name, idx, data, key_type, value_type):
        self.set_list_as_type(name + '_idx', idx, 0, data.keys(), key_type)
        self.set_list_as_type(name + '_value', idx, 0, data.items(), value_type)
        self.save_variable(name + '_length', idx, len(data))

    def load_object(self, name, idx):
        # TODO: Add logging here
        idx = int(idx)

        json_string = self.storage.variables[name][idx]

        simplified = yaml.load(json_string)
        obj = self.simplifier.build(simplified)
        setattr(obj, 'json', json_string)

        return obj

    def save_object(self, name, idx, obj):
        if not hasattr(obj,'json'):
            setattr(obj, 'json', self.object_to_json(obj))

        self.storage.variables[name][idx] = obj.json

#=============================================================================================
# CONVERSION UTILITIES
#=============================================================================================

    def object_to_json(self, obj):
        json_string = self.simplifier.to_json_object(obj, obj.base_cls_name)

        return json_string

    def list_to_numpy(self, data, value_type, allow_empty = True):
        if value_type == 'int':
            values = np.array(data).astype(np.float32)
        elif value_type == 'float':
            values = np.array(data).astype(np.float32)
        elif value_type == 'bool':
            values = np.array(data).astype(np.uint8)
        elif value_type == 'index':
            values = np.array(data).astype(np.int32)
        elif value_type == 'length':
            values = np.array(data).astype(np.int32)
        else:
            # an object
            values = [-1 if value is None and allow_empty is True else value.idx[self.storage] for value in data]
            values = np.array(values).astype(np.int32)

        return values.copy()

    def list_from_numpy(self, values, value_type, allow_empty = True):
        if value_type == 'int':
            data = values.tolist()
        elif value_type == 'float':
            data = values.tolist()
        elif value_type == 'bool':
            data = values.tolist()
        elif value_type == 'index':
            data = values.tolist()
        elif value_type == 'length':
            data = values.tolist()
        else:
            # an object
            key_store = getattr(self.storage, value_type)
            data = [key_store.load(obj_idx) if allow_empty is False or obj_idx >= 0 else None for obj_idx in values.tolist()]

        return data

#=============================================================================================
# SETTER / GETTER UTILITY FUNCTIONS
#=============================================================================================

    def get_object(self, name, idx, cls):
        index = self.load_variable(name + '_idx', idx)
        if index < 0:
            return None

        store = getattr(self.storage, cls)
        obj = store.load(index)
        return obj

    def set_object(self, name, idx, obj):
        if obj is not None:
            self.storage.variables[name + '_idx'][idx] = obj.idx[self.storage]
        else:
            self.storage.variables[name + '_idx'][idx] = -1

    def get_list_as_type(self, name, idx, begin, length, value_type):
        storage = self.storage
        values = storage.variables[name][idx, begin:begin+length]

        data = self.list_from_numpy(values, value_type)
        return data

    def set_list_as_type(self, name, idx, begin, data, value_type):
        values = self.list_to_numpy(data, value_type)
        self.storage.variables[name][idx, begin:begin+len(data)] = values

#=============================================================================================
# ORDERPARAMETER UTILITY FUNCTIONS
#=============================================================================================

    @property
    def op_idx(self):
        """
        Returns aa function that returns for an object of this storage the idx
        """
        def idx(obj):
            return obj.idx[self.storage]

        return idx

#=============================================================================
# LOAD/SAVE DECORATORS FOR PARTIAL LOADING OF ATTRIBUTES
#=============================================================================

def loadpartial(func, constructor=None):
    def inner(self, idx, *args, **kwargs):
        if hasattr(self, '_delayed_loading'):
            if constructor is None:
                obj = self.load_constructor
            else:
                obj = getattr(self, 'load_empty')
        else:
            obj = func(idx, *args, **kwargs)
        return obj

    return inner


#=============================================================================
# LOAD/SAVE DECORATORS FOR CACHE HANDLING
#=============================================================================

def loadcache(func):
    def inner(self, idx, *args, **kwargs):
        if type(idx) is not str and idx < 0:
            return None

        n_idx = idx

        # if it is in the cache, return it, otherwise not :)
        if idx in self.cache:
            cc = self.cache[idx]
            if type(cc) is int:
                # here the cached value is actually only the index
                # so it still needs to be loaded with the given index
                # this happens when we want to load by name (str)
                # and we need to actually load it
                n_idx = cc
            else:
                # we have a real object (hopefully) and just return from cache
                return self.cache[idx]

        elif type(idx) is str:
            # we want to load by name and it was not in cache.
            if self.is_named:
                # since it is not found in the cache before. Refresh the cache
                self.update_name_cache()

                # and give it another shot
                if idx in self.cache:
                    n_idx = self.cache[idx]
                else:
                    raise ValueError('str "' + idx + '" not found in storage')
            else:
                raise ValueError('str "' + idx + '" as indices are only allowed in named storage')

        # ATTENTION HERE!
        # Note that the wrapped function no self as first parameter. This is because we are wrapping a bound
        # method in an instance and this one is still bound - luckily - to the same 'self'. In a class decorator when wrapping
        # the class method directly it is not bound yet and so we need to include the self! Took me some time to
        # understand and figure that out
        obj = func(n_idx, *args, **kwargs)
        if obj is not None:
            # update cache there might have been a change due to naming
            self.cache[obj.idx[self.storage]] = obj

            # finally store the name of a named object in cache
            if self.is_named and hasattr(obj, 'name') and obj.name != '':
                self.cache[obj.name] = obj

        return obj
    return inner

# the default decorator for save functions to enable caching
def savecache(func):
    def inner(self, obj, idx = None, *args, **kwargs):
        # call the normal storage
        func(obj, idx, *args, **kwargs)

        # store the ID in the cache
        self.cache[idx] = obj
        if self.is_named and hasattr(obj, 'name') and obj.name != '':
            # and also the name, if it has one so we can load by
            # name afterwards from cache
            self.cache[obj.name] = obj

    return inner

#=============================================================================
# LOAD/SAVE DECORATORS FOR .idx HANDLING
#=============================================================================

def loadidx(func):
    def inner(self, idx, *args, **kwargs):
        if type(idx) is not str and idx < 0:
            return None

        n_idx = idx

        if type(idx) is str:
            # we want to load by name and it was not in cache
            if self.is_named:
                n_idx = self.load_by_name(idx)
            else:
                # load by name only in named storages
                raise ValueError('Load by name (str) is only supported in named storages')
                pass

        # ATTENTION HERE!
        # Note that the wrapped function ho self as first parameter. This is because we are wrapping a bound
        # method in an instance and this one is still bound - luckily - to the same 'self'. In a class decorator when wrapping
        # the class method directly it is not bound yet and so we need to include the self! Took me some time to
        # understand and figure that out
        obj = func(n_idx, *args, **kwargs)

        if not hasattr(obj, 'idx'):
            obj.idx = dict()

        obj.idx[self.storage] = n_idx

        if self.is_named and not hasattr(obj, 'name'):
            # get the name of the object
            setattr(obj, 'name', self.get_name(idx))

        return obj
    return inner

def saveidx(func):
    def inner(self, obj, idx = None, *args, **kwargs):

        storage = self.storage
        if idx is None:
            if storage in obj.idx:
                # has been saved so quit and do nothing
                return None
            else:
                idx = self.free()
                obj.idx[storage] = idx
        else:
            if type(idx) is str:
                # Not yet supported
                raise ValueError('Saving by name not yet supported')
            else:
                idx = int(idx)

        func(obj, idx, *args, **kwargs)

    return inner