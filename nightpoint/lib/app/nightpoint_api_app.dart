import 'package:flutter/material.dart';

import '../features/events/presentation/map_page.dart';
import '../features/garage/presentation/garage_page.dart';

import '../core/api/api_client.dart';
import '../core/theme/product_theme.dart';
import '../features/events/presentation/events_page.dart';
import '../features/identity/data/local_demo_identity.dart';
import '../features/identity/data/profile_repository.dart';
import '../features/identity/presentation/local_sign_in_page.dart';
import '../features/identity/presentation/profile_editor.dart';
import '../features/identity/presentation/product_avatar.dart';

class NightPointApiApp extends StatefulWidget {
  const NightPointApiApp({super.key, required this.api});
  final ApiClient api;
  @override
  State<NightPointApiApp> createState() => _NightPointApiAppState();
}

class _NightPointApiAppState extends State<NightPointApiApp> {
  ThemeMode _theme = ThemeMode.system;
  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: widget.api.session,
    builder: (context, _) => MaterialApp(
      key: ValueKey(widget.api.session.generation),
      title: 'NightPoint',
      debugShowCheckedModeBanner: false,
      theme: ProductTheme.forBrightness(Brightness.light),
      darkTheme: ProductTheme.forBrightness(Brightness.dark),
      themeMode: _theme,
      home: widget.api.session.signedIn
          ? _ProfileGate(
              key: ValueKey(widget.api.session.generation),
              api: widget.api,
              theme: _theme,
              onTheme: (value) => setState(() => _theme = value),
            )
          : LocalSignInPage(identity: LocalDemoIdentity(widget.api)),
    ),
  );
}

class _ProfileGate extends StatefulWidget {
  const _ProfileGate({
    super.key,
    required this.api,
    required this.theme,
    required this.onTheme,
  });
  final ApiClient api;
  final ThemeMode theme;
  final ValueChanged<ThemeMode> onTheme;
  @override
  State<_ProfileGate> createState() => _ProfileGateState();
}

class _ProfileGateState extends State<_ProfileGate> {
  late final ProfileRepository _repository;
  late Future<ProfileRecord> _profile;
  @override
  void initState() {
    super.initState();
    _repository = ProfileRepository(widget.api);
    _profile = _repository.read();
  }

  void _saved(ProfileRecord value) => setState(() {
    _profile = Future.value(value);
  });

  @override
  Widget build(BuildContext context) => FutureBuilder<ProfileRecord>(
    future: _profile,
    builder: (context, snapshot) {
      final profile = snapshot.data;
      if (profile != null) {
        return _Shell(
          api: widget.api,
          profile: profile,
          onProfile: _saved,
          theme: widget.theme,
          onTheme: widget.onTheme,
        );
      }
      final failure = snapshot.error;
      if (failure is ApiFailure && {404, 409}.contains(failure.status)) {
        return Scaffold(
          appBar: AppBar(
            title: const Text('NightPoint'),
            actions: [
              TextButton(
                onPressed: widget.api.session.signOut,
                child: const Text('Sair'),
              ),
            ],
          ),
          body: ProfileEditor(repository: _repository, onSaved: _saved),
        );
      }
      if (snapshot.hasError) {
        return Scaffold(
          appBar: AppBar(title: const Text('NightPoint')),
          body: Center(
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    failure is ApiFailure
                        ? failure.message
                        : 'Não foi possível carregar seu perfil.',
                  ),
                  const SizedBox(height: 16),
                  FilledButton(
                    onPressed: () {
                      final pending = _repository.read();
                      setState(() {
                        _profile = pending;
                      });
                    },
                    child: const Text('Tentar novamente'),
                  ),
                  TextButton(
                    onPressed: widget.api.session.signOut,
                    child: const Text('Sair'),
                  ),
                ],
              ),
            ),
          ),
        );
      }
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    },
  );
}

class _Shell extends StatefulWidget {
  const _Shell({
    required this.api,
    required this.profile,
    required this.onProfile,
    required this.theme,
    required this.onTheme,
  });
  final ApiClient api;
  final ProfileRecord profile;
  final ValueChanged<ProfileRecord> onProfile;
  final ThemeMode theme;
  final ValueChanged<ThemeMode> onTheme;
  @override
  State<_Shell> createState() => _ShellState();
}

class _ShellState extends State<_Shell> {
  int _index = 0;
  bool _leaving = false;

  Future<void> _editProfile() async {
    final result = await Navigator.of(context).push<ProfileRecord>(
      MaterialPageRoute(
        builder: (context) => Scaffold(
          appBar: AppBar(title: const Text('Perfil')),
          body: ProfileEditor(
            repository: ProfileRepository(widget.api),
            previous: widget.profile,
            onSaved: (profile) => Navigator.pop(context, profile),
          ),
        ),
      ),
    );
    if (result != null && mounted) widget.onProfile(result);
  }

  Future<void> _leave() async {
    setState(() => _leaving = true);
    try {
      await LocalDemoIdentity(widget.api).leave();
    } on ApiFailure {
      /* The session is cleared even if the server is unreachable. */
    } finally {
      if (mounted) setState(() => _leaving = false);
    }
  }

  Widget _home(BuildContext context) => ListView(
    padding: const EdgeInsets.all(24),
    children: [
      Align(
        alignment: Alignment.centerLeft,
        child: ProductAvatar(
          nickname: widget.profile.nickname,
          style: widget.profile.avatarStyle,
        ),
      ),
      const SizedBox(height: 24),
      Text(
        'Olá, ${widget.profile.nickname}',
        style: Theme.of(context).textTheme.headlineMedium,
      ),
      const SizedBox(height: 12),
      const Text('Seu próximo encontro começa aqui.'),
      const SizedBox(height: 24),
      Card(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Icon(Icons.directions_car_outlined, size: 44),
              const SizedBox(height: 16),
              Text(
                'Encontre sua comunidade',
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SizedBox(height: 12),
              const Text(
                'Explore encontros por região e período ou organize o seu.',
              ),
              const SizedBox(height: 20),
              FilledButton(
                onPressed: () => setState(() => _index = 2),
                child: const Text('Explorar encontros'),
              ),
            ],
          ),
        ),
      ),
      const SizedBox(height: 16),
      const Text('Ambiente acadêmico local · somente dados sintéticos.'),
    ],
  );

  Widget _profile(BuildContext context) => ListView(
    padding: const EdgeInsets.all(24),
    children: [
      Center(
        child: ProductAvatar(
          nickname: widget.profile.nickname,
          style: widget.profile.avatarStyle,
          radius: 40,
        ),
      ),
      const SizedBox(height: 24),
      Text(
        widget.profile.nickname,
        textAlign: TextAlign.center,
        style: Theme.of(context).textTheme.headlineMedium,
      ),
      const SizedBox(height: 8),
      const Text('Seu perfil privado', textAlign: TextAlign.center),
      const SizedBox(height: 24),
      Card(
        child: ListTile(
          leading: const Icon(Icons.edit_outlined),
          title: const Text('Editar perfil'),
          trailing: const Icon(Icons.chevron_right),
          onTap: _editProfile,
        ),
      ),
      Card(
        child: ListTile(
          leading: const Icon(Icons.garage_outlined),
          title: const Text('Minha garagem'),
          trailing: const Icon(Icons.chevron_right),
          onTap: () => Navigator.of(context).push<void>(
            MaterialPageRoute(builder: (_) => GaragePage(api: widget.api)),
          ),
        ),
      ),
      const SizedBox(height: 16),
      DropdownButtonFormField<ThemeMode>(
        initialValue: widget.theme,
        decoration: const InputDecoration(labelText: 'Tema'),
        items: const [
          DropdownMenuItem(value: ThemeMode.system, child: Text('Automático')),
          DropdownMenuItem(value: ThemeMode.light, child: Text('Claro')),
          DropdownMenuItem(value: ThemeMode.dark, child: Text('Escuro')),
        ],
        onChanged: (value) {
          if (value != null) widget.onTheme(value);
        },
      ),
      const SizedBox(height: 24),
      OutlinedButton.icon(
        onPressed: _leaving ? null : _leave,
        icon: const Icon(Icons.logout),
        label: const Text('Sair'),
      ),
    ],
  );

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: TextButton.icon(
        onPressed: () => setState(() => _index = 0),
        icon: const Icon(Icons.directions_car_outlined),
        label: const Text('NightPoint'),
      ),
    ),
    body: switch (_index) {
      1 => EventMapPage(api: widget.api, userId: widget.profile.userId),
      2 => EventsPage(
        key: const ValueKey('events'),
        api: widget.api,
        userId: widget.profile.userId,
      ),
      3 => EventsPage(
        key: const ValueKey('community'),
        api: widget.api,
        userId: widget.profile.userId,
        communityMode: true,
      ),
      4 => _profile(context),
      _ => _home(context),
    },
    bottomNavigationBar: NavigationBar(
      selectedIndex: _index,
      onDestinationSelected: (value) => setState(() => _index = value),
      destinations: const [
        NavigationDestination(icon: Icon(Icons.home_outlined), label: 'Início'),
        NavigationDestination(icon: Icon(Icons.map_outlined), label: 'Mapa'),
        NavigationDestination(
          icon: Icon(Icons.event_outlined),
          label: 'Eventos',
        ),
        NavigationDestination(
          icon: Icon(Icons.groups_outlined),
          label: 'Social',
        ),
        NavigationDestination(
          icon: Icon(Icons.person_outline),
          label: 'Perfil',
        ),
      ],
    ),
  );
}
