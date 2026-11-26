import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:url_launcher/url_launcher.dart';
import '../../../core/location/geolocator_location.dart';

import '../../../core/api/api_client.dart';
import '../data/event_repository.dart';
import 'event_detail_page.dart';
import 'map_model.dart';
import 'position_model.dart';

class EventMapPage extends StatefulWidget {
  const EventMapPage({super.key, required this.api, required this.userId});
  final ApiClient api;
  final String userId;

  @override
  State<EventMapPage> createState() => _EventMapPageState();
}

class _EventMapPageState extends State<EventMapPage>
    with WidgetsBindingObserver {
  late final MapModel _model;
  late final PositionModel _position;
  static const _tiles = bool.fromEnvironment(
    'NP_MAP_TILES',
    defaultValue: true,
  );
  final _controller = MapController();
  final _lat = TextEditingController(text: '-20.5386');
  final _lon = TextEditingController(text: '-47.4009');
  final _form = GlobalKey<FormState>();
  bool _foreground = true, _detail = false;
  LatLng _center = const LatLng(-20.5386, -47.4009);

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _model = MapModel(EventRepository(widget.api))
      ..load(lat: _center.latitude, lon: _center.longitude);
    _position = PositionModel(GeolocatorLocation());
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _foreground = state == AppLifecycleState.resumed;
    if (!_foreground) {
      _position.stop();
      _model.suspend();
    } else if (!_detail) {
      unawaited(_model.load());
    }
  }

  Future<void> _open(EventRecord event) async {
    _detail = true;
    _position.stop();
    _model.suspend();
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => EventDetailPage(
          api: widget.api,
          identifier: event.id,
          userId: widget.userId,
        ),
      ),
    );
    if (!mounted) return;
    _detail = false;
    if (_foreground) unawaited(_model.load());
  }

  String? _coordinate(String? value, double bound) {
    final number = double.tryParse(value ?? '');
    return number == null || !number.isFinite || number.abs() > bound
        ? 'Entre -$bound e $bound'
        : null;
  }

  void _search() {
    if (!_form.currentState!.validate()) return;
    _center = LatLng(double.parse(_lat.text), double.parse(_lon.text));
    _controller.move(_center, 12);
    unawaited(_model.load(lat: _center.latitude, lon: _center.longitude));
  }

  Future<void> _locate() async {
    await _position.start();
    if (!mounted || !_foreground || _detail) return;
    final point = _position.point;
    if (point == null) return;
    _center = LatLng(point.latitude, point.longitude);
    _lat.text = point.latitude.toStringAsFixed(6);
    _lon.text = point.longitude.toStringAsFixed(6);
    _controller.move(_center, 14);
    // Position updates stay on device. Only an explicit search sends a point.
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _model.dispose();
    _position.dispose();
    _controller.dispose();
    _lat.dispose();
    _lon.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: Listenable.merge([_model, _position]),
    builder: (context, _) => ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text(
          'Encontros no mapa',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        const SizedBox(height: 8),
        const Text(
          'Cartografia © OpenStreetMap contributors. A região visível é enviada ao provedor do mapa. '
          'A localização é opcional e fica em memória; somente Buscar envia o ponto à API. '
          'Sem rastreamento de trajetórias. Encontros de demonstração são fictícios.',
        ),
        Wrap(
          spacing: 12,
          children: [
            OutlinedButton.icon(
              onPressed: _position.busy ? null : _locate,
              icon: const Icon(Icons.my_location),
              label: Text(
                _position.busy
                    ? 'Obtendo localização...'
                    : 'Usar minha localização',
              ),
            ),
            if (_position.point != null)
              TextButton(
                onPressed: _position.stop,
                child: const Text('Parar localização'),
              ),
          ],
        ),
        if (_position.point != null)
          const Text(
            'Posição atual ativa · atualização somente neste dispositivo',
          ),
        if (_position.error != null) Text(_position.error!),
        const SizedBox(height: 12),
        Form(
          key: _form,
          child: Wrap(
            spacing: 12,
            runSpacing: 12,
            children: [
              SizedBox(
                width: 170,
                child: TextFormField(
                  controller: _lat,
                  decoration: const InputDecoration(
                    labelText: 'Latitude manual',
                  ),
                  validator: (value) => _coordinate(value, 85),
                ),
              ),
              SizedBox(
                width: 170,
                child: TextFormField(
                  controller: _lon,
                  decoration: const InputDecoration(
                    labelText: 'Longitude manual',
                  ),
                  validator: (value) => _coordinate(value, 180),
                ),
              ),
              FilledButton(
                onPressed: _model.loading ? null : _search,
                child: const Text('Buscar região'),
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        SizedBox(
          height: 340,
          child: ClipRRect(
            borderRadius: BorderRadius.circular(16),
            child: FlutterMap(
              mapController: _controller,
              options: MapOptions(
                initialCenter: _center,
                initialZoom: 12,
                minZoom: 2,
                maxZoom: 18,
                backgroundColor: Theme.of(
                  context,
                ).colorScheme.surfaceContainerHighest,
                onPositionChanged: (camera, gesture) {
                  _center = camera.center;
                },
                onTap: (_, point) {
                  _lat.text = point.latitude.toStringAsFixed(6);
                  _lon.text = point.longitude.toStringAsFixed(6);
                },
              ),
              children: [
                if (_tiles)
                  TileLayer(
                    urlTemplate:
                        'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                    userAgentPackageName: 'br.edu.nightpoint.academic',
                    panBuffer: 0,
                  ),
                MarkerLayer(
                  markers: [
                    if (_position.point case final point?)
                      Marker(
                        point: LatLng(point.latitude, point.longitude),
                        width: 36,
                        height: 36,
                        child: const Tooltip(
                          message: 'Sua posição atual',
                          child: Icon(
                            Icons.person_pin_circle,
                            color: Colors.blue,
                            size: 36,
                          ),
                        ),
                      ),
                    Marker(
                      point: LatLng(_model.latitude, _model.longitude),
                      width: 40,
                      height: 40,
                      child: const Tooltip(
                        message: 'Centro da busca',
                        child: Icon(Icons.my_location),
                      ),
                    ),
                    for (final event in _model.items)
                      Marker(
                        point: LatLng(event.latitude!, event.longitude!),
                        width: 48,
                        height: 48,
                        child: IconButton(
                          tooltip: event.title,
                          onPressed: () => _open(event),
                          icon: Icon(
                            Icons.location_on,
                            color: Theme.of(context).colorScheme.primary,
                            size: 36,
                          ),
                        ),
                      ),
                  ],
                ),
                const IgnorePointer(
                  child: Center(child: Icon(Icons.add, size: 18)),
                ),
                if (_tiles)
                  SimpleAttributionWidget(
                    source: const Text('OpenStreetMap contributors'),
                    onTap: () => launchUrl(
                      Uri.parse('https://www.openstreetmap.org/copyright'),
                    ),
                  ),
              ],
            ),
          ),
        ),
        TextButton.icon(
          onPressed: _model.loading
              ? null
              : () {
                  _lat.text = _center.latitude.toStringAsFixed(6);
                  _lon.text = _center.longitude.toStringAsFixed(6);
                  _search();
                },
          icon: const Icon(Icons.search),
          label: const Text('Buscar no centro visível · raio 10 km'),
        ),
        if (_model.loading) const LinearProgressIndicator(),
        if (_model.error != null)
          Text(
            _model.error!,
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
        if (!_model.loading && _model.error == null && _model.items.isEmpty)
          const Text(
            'Nenhum encontro publicado nesta região nos próximos 30 dias.',
          ),
        if (_model.truncated)
          const Text(
            'Exibindo até 25 encontros. Refine a região para consultar outros.',
          ),
        for (final event in _model.items)
          ListTile(
            leading: const Icon(Icons.event_outlined),
            title: Text(event.title),
            subtitle: Text(event.locationLabel),
            onTap: () => _open(event),
          ),
      ],
    ),
  );
}
