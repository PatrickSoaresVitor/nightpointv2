class CommunitySummary {
  CommunitySummary.fromJson(Map<String, dynamic> json)
    : likes = json['likes'] as int,
      participants = json['participants'] as int,
      liked = json['liked'] as bool,
      participating = json['participating'] as bool;
  final int likes, participants;
  final bool liked, participating;
}

class CommentRecord {
  CommentRecord.fromJson(Map<String, dynamic> json)
    : id = json['id'] as String,
      text = json['text'] as String,
      version = json['version'] as int,
      mine = json['mine'] as bool,
      organizer = json['organizer'] as bool,
      removed = json['removed'] as bool,
      canRemove = json['can_remove'] as bool,
      canRestore = json['can_restore'] as bool;
  final String id, text;
  final int version;
  final bool mine, organizer, removed, canRemove, canRestore;
  String get author => mine
      ? 'Você'
      : organizer
      ? 'Organizador'
      : 'Participante';
}

class CommentPage {
  const CommentPage(this.items, this.nextOffset);
  final List<CommentRecord> items;
  final int? nextOffset;
}
