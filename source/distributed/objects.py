from __future__ import annotations

import inspect
import math
from typing import Any, Callable

from panda3d.core import (
    Filename,
    Quat,
    VBase2,
    VBase3,
    VBase4,
    Vec2,
    Vec3,
    Vec4,
    VirtualFileSystem,
    getModelPath,
)
from panda3d.direct import DCClass, DCFile
from panda3d_toolbox import runtime

from direct.directnotify.DirectNotifyGlobal import directNotify
from direct.showbase.DirectObject import DirectObject

from .config import get_client_interp_amount
from .constants import DOState
from .native import (
    InterpolatedFloat,
    InterpolatedQuat,
    InterpolatedVec2,
    InterpolatedVec3,
    InterpolatedVec4,
    InterpolationContext,
)

# --------------------------------------------------------------------------------


class BaseDistributedObject(DirectObject):
    """Base class for all distributed objects (client and server).

    DO lifetime
    -----------
    __init__        – brand new, not yet alive
    generate        – alive, but baseline state not yet applied
    announce_generate – fully alive with known initial state (client-only)
    disable         – temporarily removed / cached (client-only)
    delete          – gone for good
    """

    notify = directNotify.newCategory("BaseDistributedObject")

    def __init__(self) -> None:
        self.do_id: int | None = None
        self.zone_id: int | None = None
        self.dclass: DCClass | None = None
        self.do_state: int = DOState.Fresh
        self._tasks: dict[str, tuple[Any, Any]] = {}

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}:do_id={self.do_id}"

    # -- state queries --------------------------------------------------------

    def is_do_generated(self) -> bool:
        return self.do_state >= DOState.Generated

    def is_do_alive(self) -> bool:
        return self.do_state >= DOState.Alive

    def is_do_disabled(self) -> bool:
        return self.do_state <= DOState.Disabled

    def is_do_fresh(self) -> bool:
        return self.do_state == DOState.Fresh

    def is_do_deleted(self) -> bool:
        return self.do_state == DOState.Deleted

    # -- task helpers ---------------------------------------------------------

    def add_task(
        self,
        method: Callable,
        name: str,
        extra_args: list[Any] | None = None,
        append_task: bool | None = None,
        sim: bool = True,
        sort: int = 0,
        delay: float = 0,
    ) -> Any:
        if extra_args is None:
            extra_args = []

        if name in self._tasks:
            self.remove_task(name)

        if delay <= 0:
            task = runtime.base.taskMgr.add(
                method, self.task_name(name),
                extraArgs=extra_args, appendTask=append_task, sort=sort,
            )
        else:
            task = runtime.base.taskMgr.doMethodLater(
                delay, method, self.task_name(name),
                extraArgs=extra_args, appendTask=append_task, sort=sort,
            )
        self._tasks[name] = (task, runtime.base.taskMgr)
        return task

    def remove_task(self, name: str, remove_from_table: bool = True) -> None:
        task_info = self._tasks.get(name)
        if task_info:
            task_info[0].remove()
            if remove_from_table:
                del self._tasks[name]

    def has_task(self, name: str) -> bool:
        task = self._tasks.get(name)
        return task is not None and task[0].isAlive()

    def remove_all_tasks(self) -> None:
        for task_info in self._tasks.values():
            task_info[0].remove()
        self._tasks = {}

    # -- naming helpers -------------------------------------------------------

    def unique_name(self, name: str) -> str:
        return "%s-%i" % (name, self.do_id)

    def task_name(self, name: str) -> str:
        return self.unique_name(name)

    # -- stubs ----------------------------------------------------------------

    def send_update(self, name: str, args: list[Any] | None = None) -> None:
        """Send a non-stateful event message from one object view to another."""

    def simulate(self) -> None:
        """Called once per simulation tick on predicted objects."""

    def update(self) -> None:
        """Called once per frame."""

    # -- lifecycle ------------------------------------------------------------

    def generate(self) -> None:
        self.do_state = DOState.Generated

    def announce_generate(self) -> None:
        self.do_state = DOState.Alive

    def delete(self) -> None:
        self.ignoreAll()
        self.remove_all_tasks()
        self._tasks = None  # type: ignore[assignment]
        self.zone_id = None
        self.dclass = None
        self.do_state = DOState.Deleted


# --------------------------------------------------------------------------------


class DistributedObjectAI(BaseDistributedObject):

    def __init__(self) -> None:
        BaseDistributedObject.__init__(self)
        self.owner: Any | None = None

    def send_update(
        self,
        name: str,
        args: list[Any] | None = None,
        client: Any | None = None,
        exclude_clients: list[Any] | None = None,
    ) -> None:
        if args is None:
            args = []
        if exclude_clients is None:
            exclude_clients = []
        runtime.base.sv.send_update(self, name, args, client, exclude_clients)

    def delete(self) -> None:
        self.owner = None
        BaseDistributedObject.delete(self)


# --------------------------------------------------------------------------------


class InterpVarEntry:

    def __init__(
        self,
        var: Any,
        getter: Callable,
        setter: Callable,
        flags: int,
        array_index: int,
    ) -> None:
        self.var = var
        self.getter = getter
        self.setter = setter
        self.array_index: int = array_index
        self.flags: int = flags
        self.needs_interpolation: bool = False


# --------------------------------------------------------------------------------


class DistributedObject(BaseDistributedObject):
    """Base client-side distributed object with interpolation support."""

    SIMULATION_VAR: int = 1 << 0
    ANIMATION_VAR: int = 1 << 1
    OMIT_UPDATE_LAST_NETWORKED: int = 1 << 2
    EXCLUDE_AUTO_LATCH: int = 1 << 3
    EXCLUDE_AUTO_INTERPOLATE: int = 1 << 4

    never_disable: bool = False

    interpolate_list: set[DistributedObject] = set()
    teleport_list: list[DistributedObject] = []

    def __init__(self) -> None:
        BaseDistributedObject.__init__(self)
        self.is_owner: bool = False
        self.interp_vars: list[InterpVarEntry] = []
        self.last_interpolation_time: float = 0.0

    @staticmethod
    def interpolate_objects() -> None:
        ctx = InterpolationContext()
        ctx.enable_extrapolation(True)
        ctx.set_last_timestamp(
            runtime.base.clockMgr.networkToClientTime(runtime.base.cl.last_server_tick_time)
        )
        for do in set(DistributedObject.interpolate_list):
            do.interpolate(globalClock.getFrameTime())
            do.post_interpolate()

    def get_interpolated_var_entry(self, var: Any) -> InterpVarEntry | None:
        for ent in self.interp_vars:
            if ent.var == var:
                return ent
        return None

    def add_interpolated_var(
        self,
        var: Any,
        getter: Callable,
        setter: Callable,
        flags: int = SIMULATION_VAR,
        array_index: int = -1,
    ) -> None:
        if self.get_interpolated_var_entry(var) is not None:
            return

        now: float = globalClock.frame_time

        var.set_interpolation_amount(self.get_interpolate_amount())
        if isinstance(var, InterpolatedFloat):
            default: Any = 0.0
        elif isinstance(var, InterpolatedVec3):
            default = Vec3()
        elif isinstance(var, InterpolatedQuat):
            default = Quat()
        elif isinstance(var, InterpolatedVec2):
            default = Vec2()
        elif isinstance(var, InterpolatedVec4):
            default = Vec4()
        var.reset(default)
        var.record_last_networked_value(default, now)

        self.interp_vars.append(InterpVarEntry(var, getter, setter, flags, array_index))

    def remove_interpolated_var(self, var: Any) -> None:
        entry: InterpVarEntry | None = None
        for ent in self.interp_vars:
            if ent.var == var:
                entry = ent
                break
        if entry is not None:
            self.interp_vars.remove(entry)

    def update_interpolation_amount(self) -> None:
        for entry in self.interp_vars:
            entry.var.set_interpolation_amount(self.get_interpolate_amount())

    def pre_data_update(self) -> None:
        """Called before a state snapshot is unpacked onto the object."""
        if self.is_do_alive():
            for entry in self.interp_vars:
                if entry.array_index != -1:
                    entry.setter(entry.array_index, entry.var.get_last_networked_value())
                else:
                    entry.setter(entry.var.get_last_networked_value())

    def get_interpolate_amount(self) -> float:
        if self.predictable:
            return runtime.base.intervalPerTick
        server_tick_multiple: int = 1
        return runtime.base.ticksToTime(
            runtime.base.timeToTicks(get_client_interp_amount()) + server_tick_multiple
        )

    def reset_interpolated_vars(self) -> None:
        for entry in self.interp_vars:
            if entry.array_index != -1:
                entry.var.reset(entry.getter(entry.array_index))
            else:
                entry.var.reset(entry.getter())

    def post_interpolate(self) -> None:
        """Called after the object has been interpolated."""

    def on_latch_interpolated_vars(self, change_time: float, flags: int) -> None:
        update_last_networked: bool = not (flags & self.OMIT_UPDATE_LAST_NETWORKED)

        for entry in self.interp_vars:
            if not (entry.flags & flags):
                continue
            if entry.flags & self.EXCLUDE_AUTO_LATCH:
                continue

            if entry.array_index != -1:
                val = entry.getter(entry.array_index)
            else:
                val = entry.getter()
            if entry.var.record_value(val, change_time, update_last_networked):
                entry.needs_interpolation = True

        DistributedObject.interpolate_list.add(self)

    def on_store_last_networked_value(self) -> None:
        for entry in self.interp_vars:
            if entry.flags & self.EXCLUDE_AUTO_LATCH:
                continue

            if entry.array_index != -1:
                val = entry.getter(entry.array_index)
            else:
                val = entry.getter()
            entry.var.record_last_networked_value(val, runtime.base.clockMgr.getClientTime())

    def interpolate(self, now: float) -> None:  # noqa: C901
        if self.predictable:
            now = runtime.base.localAvatar.finalPredictedTick * runtime.base.intervalPerTick
            now -= runtime.base.intervalPerTick
            now += runtime.base.clockMgr.simulationDeltaNoRemainder
            now += runtime.base.remainder

        done: bool = True
        if now < self.last_interpolation_time:
            for entry in self.interp_vars:
                entry.needs_interpolation = True

        self.last_interpolation_time = now

        for entry in self.interp_vars:
            if not entry.needs_interpolation:
                continue
            if entry.flags & self.EXCLUDE_AUTO_INTERPOLATE:
                continue

            ret: int = entry.var.interpolate(now)
            if ret == 1:
                entry.needs_interpolation = False
            else:
                done = False

            if ret != -1:
                val = entry.var.get_interpolated_value()
                good: bool = True
                if isinstance(val, (VBase4, VBase3, VBase2)):
                    good = not val.isNan()
                elif isinstance(val, float):
                    good = not math.isnan(val)

                if good:
                    if entry.array_index != -1:
                        entry.setter(entry.array_index, val)
                    else:
                        entry.setter(val)

        if done:
            DistributedObject.interpolate_list.remove(self)

    def add_to_interpolation_list(self) -> None:
        DistributedObject.interpolate_list.add(self)

    def remove_from_interpolation_list(self) -> None:
        DistributedObject.interpolate_list.discard(self)

    def post_data_update(self) -> None:
        """Called after a state snapshot has been unpacked onto the object."""
        if not self.interp_vars:
            return

        if not self.predictable:
            self.on_latch_interpolated_vars(
                runtime.base.clockMgr.getClientTime(),
                DistributedObject.SIMULATION_VAR,
            )
        else:
            self.on_store_last_networked_value()

    def send_update(self, name: str, args: list[Any] | None = None) -> None:
        if args is None:
            args = []
        runtime.base.cl.send_update(self, name, args)

    def announce_generate(self) -> None:
        self.do_state = DOState.Alive

    def disable(self) -> None:
        self.remove_from_interpolation_list()
        self.ignoreAll()
        self.remove_all_tasks()
        self.do_state = DOState.Disabled

    def delete(self) -> None:
        self.interp_vars = None  # type: ignore[assignment]
        BaseDistributedObject.delete(self)


# --------------------------------------------------------------------------------


class BaseObjectManager(DirectObject):
    notify = directNotify.newCategory("BaseObjectManager")

    def __init__(self, has_owner_view: bool) -> None:
        self.dc_files: list[str] = []
        self._has_owner_view: bool = has_owner_view
        self.dc_suffix: str = ""
        self.dc_file: DCFile = DCFile()
        self.dclasses_by_name: dict[str, DCClass] | None = None
        self.dclasses_by_number: dict[int, DCClass] | None = None
        self.hash_val: int = 0

        self.do_id_to_do: dict[int, BaseDistributedObject] = {}
        if has_owner_view:
            self.do_id_to_owner_view: dict[int, BaseDistributedObject] = {}

    def get_do(self, do_id: int) -> BaseDistributedObject | None:
        return self.do_id_to_do.get(do_id)

    def get_owner_view(self, do_id: int) -> BaseDistributedObject | None:
        return self.do_id_to_owner_view.get(do_id)

    def has_owner_view(self) -> bool:
        return self._has_owner_view

    def read_dc_files(self, dc_file_names: list[str] | str | None = None) -> None:
        dc_file = self.dc_file
        dc_file.clear()
        self.dclasses_by_name = {}
        self.dclasses_by_number = {}
        self.hash_val = 0

        vfs = VirtualFileSystem.getGlobalPtr()

        if isinstance(dc_file_names, str):
            dc_file_names = [dc_file_names]

        dc_imports: dict[str, Any] = {}
        if dc_file_names is None:
            read_result = dc_file.readAll()
            if not read_result:
                self.notify.error("Could not read dc file.")
        else:
            search_path = getModelPath().getValue()
            for dc_file_name in dc_file_names:
                pathname = Filename(dc_file_name)
                vfs.resolveFilename(pathname, search_path)
                read_result = dc_file.read(pathname)
                if not read_result:
                    self.notify.error("Could not read dc file: %s" % (pathname))

        self.hash_val = dc_file.getHash()

        # Import all modules required by the DC file.
        for n in range(dc_file.getNumImportModules()):
            module_name = dc_file.getImportModule(n)[:]

            suffix = module_name.split('/')
            module_name = suffix[0]
            suffix = suffix[1:]
            if self.dc_suffix in suffix:
                module_name += self.dc_suffix

            import_symbols: list[str] = []
            for i in range(dc_file.getNumImportSymbols(n)):
                symbol_name = dc_file.getImportSymbol(n, i)

                suffix = symbol_name.split('/')
                symbol_name = suffix[0]
                suffix = suffix[1:]
                if self.dc_suffix in suffix:
                    symbol_name += self.dc_suffix

                import_symbols.append(symbol_name)

            self._import_module(dc_imports, module_name, import_symbols)

        # Get class definitions for classes named in the DC file.
        for i in range(dc_file.getNumClasses()):
            dclass = dc_file.getClass(i)
            number = dclass.getNumber()
            class_name = dclass.getName() + self.dc_suffix

            class_def = dc_imports.get(class_name)

            if class_def is None:
                class_name = dclass.getName()
                class_def = dc_imports.get(class_name)
            if class_def is None:
                self.notify.debug("No class definition for %s." % class_name)
            else:
                if inspect.ismodule(class_def):
                    if not hasattr(class_def, class_name):
                        self.notify.warning(
                            "Module %s does not define class %s." % (class_name, class_name)
                        )
                        continue
                    class_def = getattr(class_def, class_name)

                if not inspect.isclass(class_def):
                    self.notify.error("Symbol %s is not a class name." % class_name)
                else:
                    dclass.setClassDef(class_def)

            self.dclasses_by_name[class_name] = dclass
            if number >= 0:
                self.dclasses_by_number[number] = dclass

        # Owner Views
        if self.has_owner_view():
            owner_dc_suffix = self.dc_suffix + 'OV'
            owner_import_symbols: dict[str, None] = {}

            for n in range(dc_file.getNumImportModules()):
                module_name = dc_file.getImportModule(n)

                suffix = module_name.split('/')
                module_name = suffix[0]
                suffix = suffix[1:]
                if owner_dc_suffix in suffix:
                    module_name = module_name + owner_dc_suffix

                import_syms: list[str] = []
                for i in range(dc_file.getNumImportSymbols(n)):
                    symbol_name = dc_file.getImportSymbol(n, i)

                    suffix = symbol_name.split('/')
                    symbol_name = suffix[0]
                    suffix = suffix[1:]
                    if owner_dc_suffix in suffix:
                        symbol_name += owner_dc_suffix
                    import_syms.append(symbol_name)
                    owner_import_symbols[symbol_name] = None

                self._import_module(dc_imports, module_name, import_syms)

            for i in range(dc_file.getNumClasses()):
                dclass = dc_file.getClass(i)
                if (dclass.getName() + owner_dc_suffix) in owner_import_symbols:
                    number = dclass.getNumber()
                    class_name = dclass.getName() + owner_dc_suffix

                    class_def = dc_imports.get(class_name)
                    if class_def is None:
                        self.notify.error("No class definition for %s." % class_name)
                    else:
                        if inspect.ismodule(class_def):
                            if not hasattr(class_def, class_name):
                                self.notify.error(
                                    "Module %s does not define class %s." % (class_name, class_name)
                                )
                            class_def = getattr(class_def, class_name)
                        dclass.setOwnerClassDef(class_def)
                        self.dclasses_by_name[class_name] = dclass

    def _import_module(
        self,
        dc_imports: dict[str, Any],
        module_name: str,
        import_symbols: list[str],
    ) -> None:
        """Import *module_name* and merge its symbols into *dc_imports*."""
        module = __import__(module_name, globals(), locals(), import_symbols)

        if import_symbols:
            if import_symbols == ['*']:
                if hasattr(module, "__all__"):
                    import_symbols = module.__all__
                else:
                    import_symbols = list(module.__dict__.keys())

            for symbol_name in import_symbols:
                if hasattr(module, symbol_name):
                    dc_imports[symbol_name] = getattr(module, symbol_name)
                else:
                    raise Exception(
                        'Symbol %s not defined in module %s.' % (symbol_name, module_name)
                    )
        else:
            components = module_name.split('.')
            dc_imports[components[0]] = module
