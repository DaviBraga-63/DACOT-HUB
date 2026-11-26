"""Tenant-scoped support tickets and private, individual read state."""

import asyncio
import re
import secrets
from datetime import datetime, timezone
from typing import Annotated, Literal

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, UUID4
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError


Category = Literal["technical", "usage", "suggestion", "billing", "account", "other"]
StatusFilter = Literal["all", "open", "awaiting_support", "awaiting_customer", "resolved"]
STATUSES = ("awaiting_support", "awaiting_customer", "resolved")
MESSAGE_PAGE = 30
TICKET_ORDER = [("updated_at", -1), ("_id", -1)]
NOTICE_FIELDS = {"staff": "staff_notice_seq", "restaurant": "restaurant_notice_seq"}
UNAVAILABLE = "O suporte está temporariamente indisponível. Tente novamente."


class SupportRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def private_route(request):
            try:
                response = await handler(request)
            except PyMongoError:
                # Database write errors may contain document data.
                raise HTTPException(503, UNAVAILABLE, headers={"Cache-Control": "no-store"}) from None
            response.headers["Cache-Control"] = "no-store"
            return response

        return private_route


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID4


class Reply(Operation):
    message: str = Field(min_length=1, max_length=4000)


class OpenTicket(Reply):
    subject: str = Field(min_length=1, max_length=120)
    category: Category


class ChangeStatus(Operation):
    status: Literal["resolved", "awaiting_support"]


class ReadTicket(BaseModel):
    model_config = ConfigDict(extra="forbid")
    through: int = Field(strict=True, ge=1)


async def ensure_support_indexes(db):
    await db.support_tickets.create_index("number", unique=True)
    await db.support_tickets.create_index(
        [("tenant_id", 1), ("requester_id", 1), ("request_id", 1)], unique=True
    )
    for keys in (
        TICKET_ORDER, [("tenant_id", 1), *TICKET_ORDER],
        [("status", 1), *TICKET_ORDER], [("tenant_id", 1), ("status", 1), *TICKET_ORDER],
        [("category", 1), *TICKET_ORDER],
    ):
        await db.support_tickets.create_index(keys)
    await db.support_messages.create_index([("ticket_id", 1), ("seq", -1)], unique=True)
    await db.support_messages.create_index(
        [("ticket_id", 1), ("author_type", 1), ("author_id", 1), ("request_id", 1)], unique=True
    )
    await db.support_read_states.create_index(
        [("ticket_id", 1), ("author_type", 1), ("actor_id", 1)], unique=True
    )
    await db.support_rate_limits.create_index("expires_at", expireAfterSeconds=0)


def _now():
    return datetime.now(timezone.utc)


def _date(value):
    return value.replace(tzinfo=value.tzinfo or timezone.utc).isoformat()


def _scope(user, side):
    return {"tenant_id": user["tenant_id"]} if side == "restaurant" else {}


def _reader(user, side):
    return {"actor_id": user["_id"], "author_type": side}


def _ticket_view(ticket, side, unread):
    data = {
        "id": str(ticket["_id"]),
        "number": ticket["number"],
        "subject": ticket["subject"],
        "category": ticket["category"],
        "status": ticket["status"],
        "created_at": _date(ticket["created_at"]),
        "updated_at": _date(ticket["updated_at"]),
        "last_message_preview": ticket["last_message_preview"],
        "unread": bool(unread),
    }
    if side == "staff":
        data.update(restaurant_name=ticket["restaurant_name"], requester_name=ticket["requester_name"])
    return data


def _event_view(event, user, side):
    mine = event["author_type"] == side and event["author_id"] == user["_id"]
    label = event["author_name"]
    if side == "restaurant" and event["author_type"] == "staff":
        label = "Equipe DACOT"
    return {
        "id": str(event["_id"]),
        "seq": event["seq"],
        "text": event["text"],
        "kind": event["kind"],
        "author_type": event["author_type"],
        "author_label": label,
        "is_mine": mine,
        "created_at": _date(event["created_at"]),
    }


def _event(ticket_id, tenant_id, user, side, request_id, seq, now, kind, text, status):
    return {
        "_id": ObjectId(), "ticket_id": ticket_id, "tenant_id": tenant_id, "seq": seq,
        "author_id": user["_id"], "author_type": side, "author_name": user.get("name") or "Usuário",
        "request_id": str(request_id), "kind": kind, "text": text, "status_after": status,
        "created_at": now,
    }


class Support:
    def __init__(self, db):
        self.db = db

    async def _ticket(self, ticket_id, user, side):
        if not ObjectId.is_valid(ticket_id):
            raise HTTPException(404, "Ticket não encontrado")
        ticket = await self.db.support_tickets.find_one({"_id": ObjectId(ticket_id), **_scope(user, side)})
        if ticket is None:
            raise HTTPException(404, "Ticket não encontrado")
        return ticket

    async def _rate_limit(self, identity, operation, limit, window):
        now = int(_now().timestamp())
        bucket = now // window
        key = f"{identity}:{bucket}"
        existing = {"$ifNull": ["$operations", []]}
        # The fixed window never grows beyond its limit. Concurrent retries of
        # the same operation share one admission without reserving more slots.
        update = [{"$set": {
            "expires_at": datetime.fromtimestamp((bucket + 2) * window, timezone.utc),
            "operations": {"$cond": [
                {"$lt": [{"$size": existing}, limit]},
                {"$setUnion": [existing, [operation]]}, existing,
            ]},
        }}]
        try:
            row = await self.db.support_rate_limits.find_one_and_update(
                {"_id": key}, update, upsert=True, return_document=ReturnDocument.AFTER
            )
        except DuplicateKeyError:
            row = await self.db.support_rate_limits.find_one_and_update(
                {"_id": key}, update, return_document=ReturnDocument.AFTER
            )
        if not row or operation not in row["operations"]:
            raise HTTPException(429, "Muitas solicitações. Tente novamente em instantes.")

    async def _materialize(self, ticket):
        pending = ticket.get("pending_event")
        if pending is None:
            return
        # The ticket and its latest event share an atomic commit. This slot
        # stays readable until the independent history write has completed.
        await self.db.support_messages.update_one(
            {"_id": pending["_id"]}, {"$setOnInsert": pending}, upsert=True
        )
        await self.db.support_tickets.update_one(
            {"_id": ticket["_id"], "tenant_id": ticket["tenant_id"],
             "seq": pending["seq"], "pending_event._id": pending["_id"]},
            {"$unset": {"pending_event": ""}},
        )

    async def create(self, payload, user):
        request_key = {
            "tenant_id": user["tenant_id"], "requester_id": user["_id"], "request_id": str(payload.request_id),
        }
        existing = await self.db.support_tickets.find_one(request_key)
        if existing is None:
            await self._rate_limit(f"create:{user['tenant_id']}", str(payload.request_id), 8, 3600)
            ticket_id = ObjectId()
            now = _now()
            event = _event(ticket_id, user["tenant_id"], user, "restaurant", payload.request_id,
                           1, now, "message", payload.message, "awaiting_support")
            ticket = {
                **request_key, "_id": ticket_id, "number": f"SUP-{secrets.token_hex(6).upper()}",
                "restaurant_name": user["tenant"]["name"], "requester_name": event["author_name"],
                "subject": payload.subject, "category": payload.category, "status": "awaiting_support",
                "created_at": now, "updated_at": now, "seq": 1, "staff_notice_seq": 1,
                "restaurant_notice_seq": 0, "last_message_preview": payload.message[:160],
                "pending_event": event,
            }
            try:
                await self.db.support_tickets.insert_one(ticket)
            except DuplicateKeyError:
                existing = await self.db.support_tickets.find_one(request_key)
                if existing is None:
                    raise HTTPException(503, "Não foi possível reservar um número. Tente novamente.") from None
            else:
                await self._materialize(ticket)
                return {"id": str(ticket_id)}
        first = existing.get("pending_event")
        if first is None or first["seq"] != 1:
            first = await self.db.support_messages.find_one(
                {"ticket_id": existing["_id"], "tenant_id": existing["tenant_id"], "seq": 1}
            )
        if first is None:
            raise HTTPException(503, "O histórico do ticket está temporariamente indisponível.")
        if (existing["subject"], existing["category"], first["text"]) != (
            payload.subject, payload.category, payload.message,
        ):
            raise HTTPException(409, "Esta solicitação já foi usada com outros dados.")
        await self._materialize(existing)
        return {"id": str(existing["_id"])}

    async def change(self, ticket_id, user, side, payload):
        message = isinstance(payload, Reply)
        if message:
            kind, text = "message", payload.message
            target = "awaiting_customer" if side == "staff" else "awaiting_support"
        else:
            target, text = payload.status, ""
            kind = "resolved" if target == "resolved" else "reopened"
            if kind == "resolved" and side != "staff":
                raise HTTPException(403, "Somente a equipe DACOT pode resolver o ticket.")

        admitted = False
        for _ in range(12):
            ticket = await self._ticket(ticket_id, user, side)
            canonical_id = str(ticket["_id"])
            await self._materialize(ticket)
            operation = await self.db.support_messages.find_one({
                "ticket_id": ticket["_id"], "tenant_id": ticket["tenant_id"], "author_type": side,
                "author_id": user["_id"], "request_id": str(payload.request_id),
            })
            if operation:
                if (operation["kind"], operation["text"], operation["status_after"]) != (kind, text, target):
                    raise HTTPException(409, "Esta solicitação já foi usada com outros dados.")
                return {"id": canonical_id}
            if not message:
                if ticket["status"] == target:
                    raise HTTPException(409, "O ticket já está com esse status.")
                if kind == "reopened" and ticket["status"] != "resolved":
                    raise HTTPException(409, "Somente tickets resolvidos podem ser reabertos.")
            if message and side == "staff" and ticket["status"] == "resolved":
                raise HTTPException(409, "Reabra o ticket antes de responder.")
            if not admitted:
                await self._rate_limit(f"changes:{side}:{user['_id']}", f"{canonical_id}:{payload.request_id}", 40, 60)
                admitted = True
            seq, now = ticket["seq"] + 1, _now()
            event = _event(ticket["_id"], ticket["tenant_id"], user, side, payload.request_id,
                           seq, now, kind, text, target)
            event["status_before"] = ticket["status"]
            values = {"seq": seq, "status": target, "updated_at": now, "pending_event": event}
            if message:
                values["last_message_preview"] = text[:160]
            if side == "restaurant" or kind == "reopened":
                values["staff_notice_seq"] = seq
            if side == "staff" and kind != "reopened":
                values["restaurant_notice_seq"] = seq
            if kind == "resolved":
                values.update(resolved_at=now, resolved_by=user["_id"])
            else:
                values.update(resolved_at=None, resolved_by=None)
            result = await self.db.support_tickets.update_one(
                {"_id": ticket["_id"], "tenant_id": ticket["tenant_id"], "seq": ticket["seq"],
                 "pending_event": {"$exists": False}},
                {"$set": values},
            )
            if result.matched_count:
                await self._materialize({**ticket, **values})
                return {"id": canonical_id}
        raise HTTPException(409, "O ticket foi atualizado simultaneamente. Tente novamente.")

    async def _seen(self, ids, user, side):
        states = await self.db.support_read_states.find({
            "ticket_id": {"$in": ids}, **_reader(user, side),
        }, {"ticket_id": 1, "seen_seq": 1}).to_list(len(ids))
        return {state["ticket_id"]: state["seen_seq"] for state in states}

    def _unread_pipeline(self, query, user, side):
        field = NOTICE_FIELDS[side]
        return [
            {"$match": {"$and": [query, {field: {"$gt": 0}}]}},
            {"$lookup": {
                "from": "support_read_states", "localField": "_id", "foreignField": "ticket_id",
                "pipeline": [{"$match": _reader(user, side)}, {"$project": {"seen_seq": 1, "_id": 0}}],
                "as": "reader",
            }},
            {"$match": {"$expr": {"$gt": [
                "$" + field, {"$ifNull": [{"$arrayElemAt": ["$reader.seen_seq", 0]}, 0]},
            ]}}},
        ]

    async def unread(self, user, side):
        pipeline = [*self._unread_pipeline(_scope(user, side), user, side), {"$count": "count"}]
        rows = await self.db.support_tickets.aggregate(pipeline).to_list(1)
        return {"count": rows[0]["count"] if rows else 0}

    async def _counts(self, scope):
        rows = await self.db.support_tickets.aggregate([
            {"$match": scope}, {"$group": {"_id": "$status", "count": {"$sum": 1}}},
        ]).to_list(len(STATUSES))
        return {**dict.fromkeys(STATUSES, 0), **{row["_id"]: row["count"] for row in rows}}

    async def list(self, user, side, q, status, category, unread, page, page_size):
        scope = _scope(user, side)
        query = dict(scope)
        if status == "open":
            query["status"] = {"$in": ["awaiting_support", "awaiting_customer"]}
        elif status != "all":
            query["status"] = status
        if category:
            query["category"] = category
        if q.strip():
            fields = ("number", "subject", "restaurant_name") if side == "staff" else ("number", "subject")
            pattern = {"$regex": re.escape(q.strip()), "$options": "i"}
            query["$or"] = [{field: pattern} for field in fields]
        offset = (page - 1) * page_size
        if unread:
            pipeline = [*self._unread_pipeline(query, user, side), {"$facet": {
                "items": [{"$sort": dict(TICKET_ORDER)}, {"$skip": offset}, {"$limit": page_size}],
                "total": [{"$count": "count"}],
            }}]
            rows, counts = await asyncio.gather(
                self.db.support_tickets.aggregate(pipeline).to_list(1), self._counts(scope),
            )
            items = [_ticket_view(ticket, side, True) for ticket in rows[0]["items"]]
            total = rows[0]["total"][0]["count"] if rows[0]["total"] else 0
        else:
            tickets, total, counts = await asyncio.gather(
                self.db.support_tickets.find(query).sort(TICKET_ORDER).skip(offset).limit(page_size).to_list(page_size),
                self.db.support_tickets.count_documents(query), self._counts(scope),
            )
            seen = await self._seen([ticket["_id"] for ticket in tickets], user, side) if tickets else {}
            items = [_ticket_view(ticket, side, ticket[NOTICE_FIELDS[side]] > seen.get(ticket["_id"], 0))
                     for ticket in tickets]
        return {"items": items, "total": total, "page": page, "page_size": page_size, "counts": counts}

    async def _restaurant(self, ticket):
        tenant, requester = await asyncio.gather(
            self.db.tenants.find_one({"_id": ObjectId(ticket["tenant_id"])},
                {"name": 1, "owner_name": 1, "email": 1, "mobile_phone": 1, "whatsapp_phone": 1,
                 "status": 1, "portal_owner_user_id": 1}),
            self.db.tenant_users.find_one({"_id": ObjectId(ticket["requester_id"]), "tenant_id": ticket["tenant_id"]},
                {"name": 1, "email": 1, "phone_number": 1, "whatsapp_number": 1, "status": 1}),
        )
        tenant, requester = tenant or {}, requester or {}
        owner_pointer = tenant.get("portal_owner_user_id")
        owner = requester
        if ObjectId.is_valid(owner_pointer) and owner_pointer != ticket["requester_id"]:
            owner = await self.db.tenant_users.find_one(
                {"_id": ObjectId(owner_pointer), "tenant_id": ticket["tenant_id"]},
                {"name": 1, "email": 1, "phone_number": 1, "whatsapp_number": 1},
            ) or {}
        return {
            "id": ticket["tenant_id"], "name": tenant.get("name") or ticket["restaurant_name"],
            "owner_name": tenant.get("owner_name") or owner.get("name"),
            "requester_name": requester.get("name") or ticket["requester_name"],
            "email": owner.get("email") or tenant.get("email") or None,
            "whatsapp": owner.get("phone_number") or owner.get("whatsapp_number")
            or tenant.get("mobile_phone") or tenant.get("whatsapp_phone") or None,
            "status": requester.get("status") or tenant.get("status"),
        }

    async def conversation(self, ticket_id, user, side, before):
        ticket = await self._ticket(ticket_id, user, side)
        upper = min(ticket["seq"], before - 1) if before else ticket["seq"]
        messages, seen = await asyncio.gather(
            self.db.support_messages.find({"ticket_id": ticket["_id"], "tenant_id": ticket["tenant_id"],
                "seq": {"$lte": upper}}).sort("seq", -1).limit(MESSAGE_PAGE + 1).to_list(MESSAGE_PAGE + 1),
            self._seen([ticket["_id"]], user, side),
        )
        pending = ticket.get("pending_event")
        if pending and pending["seq"] <= upper and not any(m["_id"] == pending["_id"] for m in messages):
            messages.insert(0, pending)
        page = messages[:MESSAGE_PAGE]
        data = {
            "ticket": _ticket_view(ticket, side, ticket[NOTICE_FIELDS[side]] > seen.get(ticket["_id"], 0)),
            "messages": [_event_view(event, user, side) for event in reversed(page)],
            "next_before": page[-1]["seq"] if len(messages) > MESSAGE_PAGE else None,
            "through": page[0]["seq"] if page else 0,
        }
        if side == "staff":
            data["restaurant"] = await self._restaurant(ticket)
        return data

    async def read(self, ticket_id, user, side, through):
        ticket = await self._ticket(ticket_id, user, side)
        if through > ticket["seq"]:
            raise HTTPException(422, "A leitura deve corresponder a mensagens carregadas.")
        query = {"ticket_id": ticket["_id"], **_reader(user, side)}
        update = {"$max": {"seen_seq": through}, "$setOnInsert": {"tenant_id": ticket["tenant_id"]}}
        try:
            await self.db.support_read_states.update_one(query, update, upsert=True)
        except DuplicateKeyError:
            await self.db.support_read_states.update_one(query, update)
        return {"ok": True}


def support_router(db, get_restaurant_user, get_staff_write):
    api = APIRouter()
    service = Support(db)

    async def require_owner(user=Depends(get_restaurant_user)):
        if user.get("role") not in {"admin", "manager"}:
            raise HTTPException(403, "Acesso restrito à administração do restaurante.")
        return user

    def routes(prefix, dependency, side):
        router = APIRouter(prefix=prefix, tags=["suporte"], route_class=SupportRoute)

        @router.get("/unread")
        async def unread_tickets(user=Depends(dependency)):
            return await service.unread(user, side)

        @router.get("/tickets")
        async def list_tickets(
            q: Annotated[str, Query(max_length=120)] = "",
            status: StatusFilter = "all",
            category: Category | None = None,
            unread: bool = False,
            page: Annotated[int, Query(ge=1, le=1000)] = 1,
            page_size: Annotated[int, Query(ge=1, le=50)] = 20,
            user=Depends(dependency),
        ):
            return await service.list(user, side, q, status, category, unread, page, page_size)

        @router.get("/tickets/{ticket_id}")
        async def ticket_conversation(
            ticket_id: str,
            before: Annotated[int | None, Query(ge=1)] = None,
            user=Depends(dependency),
        ):
            return await service.conversation(ticket_id, user, side, before)

        @router.post("/tickets/{ticket_id}/messages")
        async def send_reply(ticket_id: str, payload: Reply, user=Depends(dependency)):
            return await service.change(ticket_id, user, side, payload)

        @router.post("/tickets/{ticket_id}/status")
        async def change_ticket_status(ticket_id: str, payload: ChangeStatus, user=Depends(dependency)):
            return await service.change(ticket_id, user, side, payload)

        @router.post("/tickets/{ticket_id}/read")
        async def mark_read(ticket_id: str, payload: ReadTicket, user=Depends(dependency)):
            return await service.read(ticket_id, user, side, payload.through)

        if side == "restaurant":
            @router.post("/tickets")
            async def create_ticket(payload: OpenTicket, user=Depends(dependency)):
                return await service.create(payload, user)

        return router

    api.include_router(routes("/portal/support", require_owner, "restaurant"))
    api.include_router(routes("/hub/support", get_staff_write, "staff"))
    return api
