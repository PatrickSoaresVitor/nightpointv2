import 'package:flutter/material.dart';

import '../../../core/api/api_client.dart';
import '../data/profile_repository.dart';
import 'product_avatar.dart';

class ProfileEditor extends StatefulWidget {
  const ProfileEditor({
    super.key,
    required this.repository,
    required this.onSaved,
    this.previous,
  });
  final ProfileRepository repository;
  final ProfileRecord? previous;
  final ValueChanged<ProfileRecord> onSaved;
  @override
  State<ProfileEditor> createState() => _ProfileEditorState();
}

class _ProfileEditorState extends State<ProfileEditor> {
  final _form = GlobalKey<FormState>();
  late final TextEditingController _nickname;
  bool _busy = false;
  String? _error;
  late String _style;
  @override
  void initState() {
    super.initState();
    _nickname = TextEditingController(
      text: widget.previous?.nickname ?? 'Participante sintético',
    );
    _style = widget.previous?.avatarStyle ?? 'np-initials';
  }

  @override
  void dispose() {
    _nickname.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (_busy || !_form.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final previous = widget.previous;
      final result = previous == null
          ? await widget.repository.provision(
              _nickname.text.trim(),
              avatarStyle: _style,
            )
          : await widget.repository.update(
              previous,
              nickname: _nickname.text.trim(),
              avatarStyle: _style,
              avatarSeed: previous.avatarSeed,
            );
      if (mounted) widget.onSaved(result);
    } on ApiFailure catch (failure) {
      if (mounted) setState(() => _error = failure.message);
    } on Exception {
      if (mounted) setState(() => _error = 'Não foi possível salvar o perfil.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Form(
    key: _form,
    child: ListView(
      padding: const EdgeInsets.all(24),
      children: [
        Text(
          widget.previous == null ? 'Seu perfil' : 'Editar perfil',
          style: Theme.of(context).textTheme.headlineMedium,
        ),
        const SizedBox(height: 12),
        const Text('A personalização é opcional. Seu perfil é privado.'),
        const SizedBox(height: 16),
        Center(
          child: ProductAvatar(nickname: _nickname.text, style: _style),
        ),
        const SizedBox(height: 24),
        TextFormField(
          controller: _nickname,
          maxLength: 80,
          enabled: !_busy,
          onChanged: (_) => setState(() {}),
          decoration: const InputDecoration(
            labelText: 'Apelido de demonstração',
          ),
          validator: (value) => value == null || value.trim().isEmpty
              ? 'Informe um apelido.'
              : null,
        ),
        DropdownButtonFormField<String>(
          initialValue: _style,
          decoration: const InputDecoration(
            labelText: 'Representação do perfil',
          ),
          items: [
            for (final entry in ProductAvatar.styles.entries)
              DropdownMenuItem(value: entry.key, child: Text(entry.value)),
            if (!ProductAvatar.styles.containsKey(_style))
              DropdownMenuItem(
                value: _style,
                child: const Text('Manter estilo anterior (exibição local)'),
              ),
          ],
          onChanged: _busy
              ? null
              : (value) {
                  if (value != null) setState(() => _style = value);
                },
        ),
        if (_error != null)
          Padding(
            padding: const EdgeInsets.all(12),
            child: Text(
              _error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ),
        const SizedBox(height: 16),
        FilledButton(
          onPressed: _busy ? null : _save,
          child: Text(_busy ? 'Salvando...' : 'Salvar perfil'),
        ),
      ],
    ),
  );
}
