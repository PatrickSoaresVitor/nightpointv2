import '../../../core/api/api_client.dart';

import '../models/profile_record.dart';
export '../models/profile_record.dart';

class ProfileRepository {
  const ProfileRepository(this.api);
  final ApiClient api;

  Future<ProfileRecord> read() async {
    final response = await api.request('GET', '/api/v1/me/profile');
    return ProfileRecord.fromJson(response.data as Map<String, dynamic>);
  }

  Future<ProfileRecord> provision(
    String nickname, {
    String? avatarStyle,
  }) async {
    final values = <String, Object?>{'nickname': nickname};
    if (avatarStyle != null) values['avatar_style'] = avatarStyle;
    final response = await api.request(
      'PUT',
      '/api/v1/me/profile',
      body: values,
    );
    return ProfileRecord.fromJson(response.data as Map<String, dynamic>);
  }

  Future<ProfileRecord> update(
    ProfileRecord previous, {
    required String nickname,
    String? avatarStyle,
    String? avatarSeed,
  }) async {
    final response = await api.request(
      'PATCH',
      '/api/v1/me/profile',
      headers: {'If-Match': '"${previous.version}"'},
      body: {
        'nickname': nickname,
        'avatar_style': avatarStyle,
        'avatar_seed': avatarSeed,
      },
    );
    return ProfileRecord.fromJson(response.data as Map<String, dynamic>);
  }
}
