"""Persistent instance configurations and independently owned process managers."""
import asyncio
import dataclasses
from uuid import uuid4
from pathlib import Path

import psutil
from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.discovery import _binary_key
from app.process_manager import ProcessManager, _port_is_free
from app.schemas import FlagValues, ResponseModel, StatusResponse
from app.storage import JsonDocumentStore


class InstanceConfig(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    port: int = Field(default=8080, ge=1, le=65535)
    model_id: str | None = None
    flags: FlagValues = Field(default_factory=dict)


class InstanceRecord(InstanceConfig):
    id: str
    pid: int | None = None
    created_at: float | None = None
    running_model_id: str | None = None
    running_flags: FlagValues = Field(default_factory=dict)


class InstanceView(ResponseModel):
    id: str
    name: str
    port: int
    model_id: str | None
    flags: FlagValues
    status: StatusResponse


class InstanceRegistry:
    def __init__(self, settings, client):
        self.settings = settings
        self.client = client
        self.lock = asyncio.Lock()
        self.store = JsonDocumentStore(settings.data_dir / 'instances.json', key='instances',
                                       version=1, migrations={0: lambda value: value}, empty=list)
        self.records = {r.id: r for r in (InstanceRecord.model_validate(v) for v in self.store.load())}
        if not self.records:
            self.records['default'] = InstanceRecord(id='default', name='Local server')
        self.managers = {}
        for record in self.records.values():
            self._make_manager(record)
        self.save()

    def _make_manager(self, record):
        # Preserve the original log path for the migrated single-server instance.
        settings = self.settings if record.id == 'default' else dataclasses.replace(
            self.settings, data_dir=self.settings.data_dir / 'instances' / record.id)
        manager = ProcessManager(settings, self.client)
        self.managers[record.id] = manager
        manager.on_started = lambda: self.checkpoint(record.id)
        if record.pid and record.created_at is not None:
            try:
                proc = psutil.Process(record.pid)
                if (proc.create_time() == record.created_at and
                        (_binary_key(proc.name()) == _binary_key(self.settings.server_bin) or
                         Path(proc.exe()).resolve() == Path(self.settings.server_bin).resolve())):
                    manager.adopt(record.pid, record.running_model_id, record.running_flags)
            except (psutil.Error, OSError):
                pass
        return manager

    def get(self, id):
        if id not in self.records:
            raise HTTPException(404, 'Server instance not found')
        return self.records[id], self.managers[id]

    def save(self):
        self.store.save([r.model_dump() for r in self.records.values()])

    def checkpoint(self, id):
        record, manager = self.get(id)
        record.pid = manager._pid if manager.state in ("running", "starting", "stopping") else None
        record.created_at = manager._process_created_at
        record.running_model_id = manager._model_id
        record.running_flags = dict(manager._flags)
        self.save()

    def port_assigned(self, port, exclude=None):
        return any(r.id != exclude and r.port == port for r in self.records.values()) or any(
            key != exclude and m.state in ('running', 'starting', 'stopping') and m._endpoint()[1] == port
            for key, m in self.managers.items())

    def validate_config(self, config, id=None):
        if not config.name.strip():
            raise HTTPException(422, 'Instance name must not be blank')
        if self.port_assigned(config.port, id):
            raise HTTPException(409, f'Port {config.port} is assigned to another instance')
        # Port is owned by the instance, not by a reusable launch preset.
        config.flags = {k: v for k, v in config.flags.items() if k != 'port'}

    def create(self, config):
        self.validate_config(config)
        record = InstanceRecord(id=uuid4().hex, **config.model_dump())
        self.records[record.id] = record
        self._make_manager(record)
        self.save()
        return record

    def update(self, id, config):
        record, manager = self.get(id)
        self.validate_config(config, id)
        if record.port != config.port and (manager.state in ('running', 'starting', 'stopping') or manager.restart_pending):
            raise HTTPException(409, 'Stop this instance before changing its port')
        for key, value in config.model_dump().items():
            setattr(record, key, value)
        self.save()
        return record

    async def delete(self, id):
        record, manager = self.get(id)
        if id == 'default':
            raise HTTPException(409, 'The default instance is retained for legacy API compatibility')
        if manager.state in ('running', 'starting', 'stopping') or manager.restart_pending:
            raise HTTPException(409, 'Stop this instance before deleting it')
        await manager.shutdown()
        del self.records[id]
        del self.managers[id]
        self.save()

    async def view(self, id):
        record, manager = self.get(id)
        return InstanceView(**{k: getattr(record, k) for k in ('id', 'name', 'port', 'model_id', 'flags')},
                            status=await manager.status())

    async def ensure_port(self, id, flags, restarting=False):
        record, manager = self.get(id)
        try:
            port = int(flags.get('port') or record.port)
        except (TypeError, ValueError):
            raise HTTPException(422, 'Port must be an integer between 1 and 65535')
        if not 1 <= port <= 65535:
            raise HTTPException(422, 'Port must be between 1 and 65535')
        if self.port_assigned(port, id):
            raise HTTPException(409, f'Port {port} is assigned to another instance')
        host = str(flags.get('host') or '127.0.0.1')
        if not restarting or manager._endpoint() != (host, port):
            if not await asyncio.to_thread(_port_is_free, host, port):
                raise HTTPException(409, f'Address {host}:{port} is unavailable')

    async def shutdown(self):
        try:
            for id in self.records:
                self.checkpoint(id)
        finally:
            await asyncio.gather(*(m.shutdown() for m in self.managers.values()))
