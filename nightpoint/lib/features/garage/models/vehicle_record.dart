class VehicleRecord {
  VehicleRecord.fromJson(Map<String, dynamic> json)
    : id = json['id'] as String,
      version = json['version'] as int,
      brand = json['brand'] as String,
      model = json['model'] as String,
      year = json['year'] as int?,
      color = json['color'] as String?,
      category = json['category'] as String,
      primary = json['primary'] as bool,
      archived = json['archived'] as bool;
  final String id, brand, model, category;
  final String? color;
  final int version;
  final int? year;
  final bool primary, archived;

  Map<String, Object?> values({bool? isPrimary, bool? isArchived}) => {
    'brand': brand,
    'model': model,
    'year': year,
    'color': color,
    'category': category,
    'primary': isPrimary ?? primary,
    'archived': isArchived ?? archived,
  };
}

class VehiclePage {
  const VehiclePage(this.items, this.nextOffset);
  final List<VehicleRecord> items;
  final int? nextOffset;
}

class VehicleRevision {
  VehicleRevision.fromJson(Map<String, dynamic> json)
    : version = json['version'] as int,
      kind = json['kind'] as String;
  final int version;
  final String kind;
}
