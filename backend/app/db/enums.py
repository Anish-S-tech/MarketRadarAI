from enum import StrEnum


class Role(StrEnum):
    admin = "admin"
    executive = "executive"
    product = "product"
    sales = "sales"
    marketing = "marketing"
    pricing = "pricing"


BUSINESS_ROLES = [Role.executive, Role.product, Role.sales, Role.marketing, Role.pricing]


class SourceType(StrEnum):
    webpage = "webpage"
    pricing = "pricing"
    blog_rss = "blog_rss"
    news = "news"
    sec_filing = "sec_filing"
    sitemap = "sitemap"
    changelog = "changelog"


FEED_SOURCE_TYPES = {SourceType.blog_rss, SourceType.news, SourceType.sec_filing, SourceType.sitemap}


class ChangeCategory(StrEnum):
    pricing = "pricing"
    product = "product"
    feature = "feature"
    positioning = "positioning"
    partnership = "partnership"
    strategy = "strategy"
    leadership = "leadership"
    financial = "financial"
    other = "other"


class Priority(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"

    @property
    def rank(self) -> int:
        return PRIORITY_RANK[self]


PRIORITY_RANK = {Priority.low: 0, Priority.medium: 1, Priority.high: 2, Priority.critical: 3}


class ConfidenceLevel(StrEnum):
    confirmed = "confirmed"
    likely = "likely"
    unverified = "unverified"
    disputed = "disputed"


class EventStatus(StrEnum):
    new = "new"
    acknowledged = "acknowledged"
    actioned = "actioned"
    dismissed = "dismissed"


class Stance(StrEnum):
    supports = "supports"
    contradicts = "contradicts"
    irrelevant = "irrelevant"
    unknown = "unknown"


class RelationshipType(StrEnum):
    partner = "partner"
    investor = "investor"
    acquirer = "acquirer"
    acquired = "acquired"
    integration = "integration"
    customer = "customer"
    supplier = "supplier"
    competitor = "competitor"


class AlertChannel(StrEnum):
    in_app = "in_app"
    email = "email"


class AlertStatus(StrEnum):
    pending = "pending"
    sent = "sent"
    failed = "failed"
    throttled = "throttled"
    deferred = "deferred"  # batched into the daily brief


class RunStatus(StrEnum):
    running = "running"
    succeeded = "succeeded"
    skipped = "skipped"
    failed = "failed"
    dead_letter = "dead_letter"
