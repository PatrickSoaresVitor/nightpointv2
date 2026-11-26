class ProfileRecord {
  ProfileRecord.fromJson(Map<String, dynamic> json)
    : userId = json['user_id'] as String,
      nickname = json['nickname'] as String,
      avatarStyle = json['avatar_style'] as String?,
      avatarSeed = json['avatar_seed'] as String?,
      version = json['version'] as int;

  final String userId, nickname;
  final String? avatarStyle, avatarSeed;
  final int version;
}
