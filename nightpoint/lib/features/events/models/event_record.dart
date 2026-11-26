class EventRecord {
  EventRecord.fromJson(Map<String, dynamic> json)
    : id = json['id'] as String,
      title = json['title'] as String,
      category = json['category_code'] as String,
      startsAt = DateTime.parse(json['starts_at'] as String),
      locationLabel = json['location_label'] as String,
      version = json['version'] as int,
      longitude = (json['longitude'] as num?)?.toDouble(),
      latitude = (json['latitude'] as num?)?.toDouble(),
      description = json['description'] as String?,
      organizerId = json['organizer_id'] as String?,
      visibility = json['visibility'] as String? ?? 'listed',
      state = json['state'] as String? ?? 'published';

  final String id, title, category, locationLabel, state, visibility;
  final String? description, organizerId;
  final DateTime startsAt;
  final int version;
  final double? longitude, latitude;
}

class EventPage {
  const EventPage(this.items, this.nextCursor);
  final List<EventRecord> items;
  final String? nextCursor;
}

class OwnedEventPage {
  const OwnedEventPage(this.items, this.nextOffset);
  final List<EventRecord> items;
  final int? nextOffset;
}
