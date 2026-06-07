from datetime import datetime, timezone

from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Boolean, ForeignKey, Text, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship

from src.database.connection import Base


class Brand(Base):
    __tablename__ = "brands"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    slug = Column(String(100), unique=True, nullable=False)

    models = relationship("Model", back_populates="brand", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Brand(id={self.id}, name='{self.name}')>"


class Model(Base):
    __tablename__ = "models"

    id = Column(Integer, primary_key=True, autoincrement=True)
    brand_id = Column(Integer, ForeignKey("brands.id"), nullable=False, index=True)
    name = Column(String(150), nullable=False)
    slug = Column(String(150), nullable=False)
    generation = Column(String(100), nullable=True)
    year_from = Column(Integer, nullable=True)
    year_to = Column(Integer, nullable=True)

    brand = relationship("Brand", back_populates="models")
    listings = relationship("Listing", back_populates="model")

    __table_args__ = (
        UniqueConstraint("brand_id", "slug", name="uq_model_brand_slug"),
    )

    def __repr__(self):
        return f"<Model(id={self.id}, brand='{self.brand.name if self.brand else None}', name='{self.name}')>"


class Listing(Base):
    __tablename__ = "listings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    brand_id = Column(Integer, ForeignKey("brands.id"), nullable=True, index=True)
    model_id = Column(Integer, ForeignKey("models.id"), nullable=True, index=True)

    source = Column(String(50), nullable=False, index=True)
    source_id = Column(String(100), nullable=False)
    url = Column(Text, nullable=False)

    raw_title = Column(Text, nullable=False)
    raw_brand = Column(String(200), nullable=True)
    raw_model = Column(String(200), nullable=True)

    year = Column(Integer, nullable=True)
    price = Column(Float, nullable=True)
    currency = Column(String(10), nullable=True, default="CLP")
    mileage_km = Column(Integer, nullable=True)
    location = Column(String(200), nullable=True)
    transmission = Column(String(50), nullable=True)
    fuel_type = Column(String(50), nullable=True)
    color = Column(String(50), nullable=True)

    is_sold = Column(Boolean, default=False, index=True)
    sold_at = Column(DateTime(timezone=True), nullable=True)

    first_seen = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_seen = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    scraped_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    extra_data = Column(Text, nullable=True)

    brand = relationship("Brand")
    model = relationship("Model", back_populates="listings")
    snapshots = relationship("ListingSnapshot", back_populates="listing", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_listing_source_id"),
        Index("ix_listings_price", "price"),
        Index("ix_listings_year", "year"),
    )

    def __repr__(self):
        return f"<Listing(id={self.id}, source='{self.source}', title='{self.raw_title[:50]}...')>"


class ListingSnapshot(Base):
    __tablename__ = "listing_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=False, index=True)
    price = Column(Float, nullable=True)
    is_sold = Column(Boolean, default=False)
    scraped_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    listing = relationship("Listing", back_populates="snapshots")

    def __repr__(self):
        return f"<Snapshot(id={self.id}, listing_id={self.listing_id}, price={self.price})>"
