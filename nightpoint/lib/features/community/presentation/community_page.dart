import 'package:flutter/material.dart';
import '../../../core/api/api_client.dart';
import '../../events/data/event_updates.dart';
import '../data/community_repository.dart';
import 'community_model.dart';

class CommunityPage extends StatefulWidget {
  const CommunityPage({
    super.key,
    required this.api,
    required this.eventId,
    required this.title,
  });
  final ApiClient api;
  final String eventId, title;
  @override
  State<CommunityPage> createState() => _CommunityPageState();
}

class _CommunityPageState extends State<CommunityPage>
    with WidgetsBindingObserver {
  late final CommunityModel _model;
  final _text = TextEditingController();
  String? _draftError;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _model = CommunityModel(
      CommunityRepository(widget.api),
      widget.eventId,
      EventUpdates(widget.api.configuration, widget.api.session),
    )..start();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _model.start();
    } else {
      _model.suspend();
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _model.dispose();
    _text.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final draft = _text.text.trim();
    if (draft.isEmpty || draft.length > 1000) {
      setState(
        () => _draftError = draft.isEmpty
            ? 'Escreva um comentário.'
            : 'Use até 1000 caracteres.',
      );
      return;
    }
    setState(() => _draftError = null);
    if (await _model.send(_text.text) && mounted) _text.clear();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('Comunidade do encontro'),
      actions: [
        IconButton(
          onPressed: () => _model.load(),
          tooltip: 'Atualizar interações',
          icon: const Icon(Icons.refresh),
        ),
      ],
    ),
    body: ListenableBuilder(
      listenable: _model,
      builder: (context, _) {
        final summary = _model.summary;
        final busy = _model.loading || _model.saving;
        return ListView(
          padding: const EdgeInsets.all(20),
          children: [
            Text(widget.title, style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 16),
            SizedBox(
              height: 4,
              child: _model.loading ? const LinearProgressIndicator() : null,
            ),
            if (_model.error != null)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 12),
                child: Text(
                  _model.error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ),
            if (summary != null) ...[
              Wrap(
                spacing: 12,
                runSpacing: 12,
                children: [
                  OutlinedButton.icon(
                    onPressed: busy
                        ? null
                        : () => _model.react('like', !summary.liked),
                    icon: Icon(
                      summary.liked ? Icons.favorite : Icons.favorite_border,
                    ),
                    label: Text(
                      '${summary.likes} · ${summary.liked ? 'Descurtir' : 'Curtir'}',
                    ),
                  ),
                  OutlinedButton.icon(
                    onPressed: busy
                        ? null
                        : () => _model.react(
                            'participation',
                            !summary.participating,
                          ),
                    icon: Icon(
                      summary.participating
                          ? Icons.check_circle
                          : Icons.group_add_outlined,
                    ),
                    label: Text(
                      '${summary.participants} · ${summary.participating ? 'Sair da participação' : 'Participar'}',
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 24),
              TextField(
                key: const ValueKey('comment-draft'),
                controller: _text,
                enabled: !_model.saving,
                maxLength: 1000,
                minLines: 2,
                maxLines: 5,
                decoration: InputDecoration(
                  labelText: 'Seu comentário',
                  errorText: _draftError,
                ),
                onChanged: (_) {
                  if (_draftError != null) setState(() => _draftError = null);
                },
              ),
              FilledButton(
                onPressed: busy ? null : _send,
                child: const Text('Enviar comentário'),
              ),
              const Divider(height: 40),
              if (_model.comments.isEmpty && !_model.loading)
                const Text('Nenhum comentário. Comece a conversa.'),
              for (final comment in _model.comments)
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          comment.author,
                          style: Theme.of(context).textTheme.labelLarge,
                        ),
                        const SizedBox(height: 8),
                        Text(comment.text),
                        if (comment.removed)
                          const Text(
                            'Retirado · visível somente para você restaurar',
                          ),
                        if (comment.canRemove)
                          TextButton.icon(
                            onPressed: busy
                                ? null
                                : () => _model.visibility(comment, true),
                            icon: const Icon(Icons.hide_source),
                            label: const Text('Retirar comentário'),
                          ),
                        if (comment.canRestore)
                          TextButton.icon(
                            onPressed: busy
                                ? null
                                : () => _model.visibility(comment, false),
                            icon: const Icon(Icons.restore),
                            label: const Text('Restaurar comentário'),
                          ),
                      ],
                    ),
                  ),
                ),
              if (_model.hasMore)
                TextButton(
                  onPressed: busy ? null : () => _model.load(reset: false),
                  child: const Text('Carregar mais'),
                ),
            ],
          ],
        );
      },
    ),
  );
}
