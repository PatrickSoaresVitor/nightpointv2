import 'package:flutter/material.dart';
import '../../../core/api/api_client.dart';
import '../data/garage_repository.dart';
import 'garage_model.dart';
import 'vehicle_detail_model.dart';
import 'vehicle_editor.dart';

class GaragePage extends StatefulWidget {
  const GaragePage({super.key, required this.api});
  final ApiClient api;
  @override
  State<GaragePage> createState() => _GaragePageState();
}

class _GaragePageState extends State<GaragePage> {
  late final GarageModel _model;
  @override
  void initState() {
    super.initState();
    _model = GarageModel(GarageRepository(widget.api))..load();
  }

  @override
  void dispose() {
    _model.dispose();
    super.dispose();
  }

  Future<void> _create() async {
    final result = await Navigator.of(context).push<VehicleRecord>(
      MaterialPageRoute(
        builder: (_) => VehicleEditor(repository: _model.repository),
      ),
    );
    if (mounted && result != null) await _model.load();
  }

  Future<void> _open(VehicleRecord vehicle) async {
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => VehicleDetailPage(
          repository: _model.repository,
          identifier: vehicle.id,
        ),
      ),
    );
    if (mounted) await _model.load();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('Minha garagem'),
      actions: [
        IconButton(
          onPressed: () => _model.load(),
          tooltip: 'Atualizar garagem',
          icon: const Icon(Icons.refresh),
        ),
      ],
    ),
    body: ListenableBuilder(
      listenable: _model,
      builder: (context, _) => ListView(
        padding: const EdgeInsets.all(20),
        children: [
          const Text('Privada · múltiplos veículos · principal opcional'),
          SwitchListTile(
            title: const Text('Mostrar arquivados'),
            value: _model.archived,
            onChanged: _model.loading
                ? null
                : (v) => _model.load(showArchived: v),
          ),
          if (_model.loading) const LinearProgressIndicator(),
          if (_model.error != null)
            Text(
              _model.error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          if (!_model.loading && _model.error == null && _model.items.isEmpty)
            const Padding(
              padding: EdgeInsets.all(24),
              child: Text(
                'Nenhum veículo aqui. Adicione seu primeiro veículo ou consulte os arquivados.',
              ),
            ),
          for (final vehicle in _model.items)
            Card(
              child: ListTile(
                leading: Icon(
                  vehicle.primary ? Icons.star : Icons.directions_car_outlined,
                ),
                title: Text('${vehicle.brand} ${vehicle.model}'),
                subtitle: Text(
                  [
                    if (vehicle.year != null) '${vehicle.year}',
                    if (vehicle.color != null) vehicle.color!,
                    if (vehicle.primary) 'Principal',
                    if (vehicle.archived) 'Arquivado',
                  ].join(' · '),
                ),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => _open(vehicle),
              ),
            ),
          if (_model.hasMore)
            TextButton(
              onPressed: _model.loading
                  ? null
                  : () => _model.load(reset: false),
              child: const Text('Carregar mais'),
            ),
          const SizedBox(height: 90),
        ],
      ),
    ),
    floatingActionButton: FloatingActionButton.extended(
      onPressed: _create,
      icon: const Icon(Icons.add),
      label: const Text('Adicionar veículo'),
    ),
  );
}

class VehicleDetailPage extends StatefulWidget {
  const VehicleDetailPage({
    super.key,
    required this.repository,
    required this.identifier,
  });
  final GarageRepository repository;
  final String identifier;
  @override
  State<VehicleDetailPage> createState() => _VehicleDetailPageState();
}

class _VehicleDetailPageState extends State<VehicleDetailPage> {
  late final VehicleDetailModel _model;
  @override
  void initState() {
    super.initState();
    _model = VehicleDetailModel(widget.repository, widget.identifier)..load();
  }

  @override
  void dispose() {
    _model.dispose();
    super.dispose();
  }

  Future<void> _edit(VehicleRecord vehicle) async {
    final result = await Navigator.of(context).push<VehicleRecord>(
      MaterialPageRoute(
        builder: (_) =>
            VehicleEditor(repository: widget.repository, previous: vehicle),
      ),
    );
    if (mounted && result != null) await _model.load();
  }

  Future<void> _archive(VehicleRecord vehicle) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(
          vehicle.archived ? 'Restaurar veículo?' : 'Arquivar veículo?',
        ),
        content: Text(
          vehicle.archived
              ? 'O veículo voltará à garagem ativa, sem alterar o principal.'
              : 'O veículo sairá da lista ativa. Você poderá restaurá-lo nos arquivados.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Voltar'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Confirmar'),
          ),
        ],
      ),
    );
    if (mounted && confirmed == true) {
      await _model.change(archived: !vehicle.archived);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('Veículo'),
      actions: [
        IconButton(
          onPressed: () => _model.load(),
          tooltip: 'Atualizar veículo',
          icon: const Icon(Icons.refresh),
        ),
      ],
    ),
    body: ListenableBuilder(
      listenable: _model,
      builder: (context, _) {
        final vehicle = _model.vehicle;
        return ListView(
          padding: const EdgeInsets.all(24),
          children: [
            if (_model.loading) const LinearProgressIndicator(),
            if (_model.error != null)
              Text(
                _model.error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            if (vehicle != null) ...[
              const Icon(Icons.directions_car_outlined, size: 72),
              const SizedBox(height: 20),
              Text(
                '${vehicle.brand} ${vehicle.model}',
                style: Theme.of(context).textTheme.headlineMedium,
              ),
              Text(
                '${vehicle.year ?? 'Ano não informado'} · ${vehicle.color ?? 'Cor não informada'}',
              ),
              Text(
                {
                  'car': 'Carro',
                  'motorcycle': 'Moto',
                  'truck': 'Caminhão',
                  'other': 'Outro',
                }[vehicle.category]!,
              ),
              if (vehicle.primary) const Chip(label: Text('Principal')),
              if (vehicle.archived) const Chip(label: Text('Arquivado')),
              const SizedBox(height: 24),
              FilledButton.icon(
                onPressed: _model.saving ? null : () => _edit(vehicle),
                icon: const Icon(Icons.edit_outlined),
                label: const Text('Editar veículo'),
              ),
              if (!vehicle.archived)
                OutlinedButton.icon(
                  onPressed: _model.saving
                      ? null
                      : () => _model.change(primary: !vehicle.primary),
                  icon: const Icon(Icons.star_outline),
                  label: Text(
                    vehicle.primary
                        ? 'Remover principal'
                        : 'Definir como principal',
                  ),
                ),
              TextButton(
                onPressed: _model.saving ? null : () => _archive(vehicle),
                child: Text(
                  vehicle.archived ? 'Restaurar veículo' : 'Arquivar veículo',
                ),
              ),
              const Divider(height: 40),
              Text(
                'Histórico privado · últimas 25 revisões',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              for (final revision in _model.history)
                ListTile(
                  leading: const Icon(Icons.history),
                  title: Text('Revisão ${revision.version}'),
                  subtitle: Text(
                    {
                          'created': 'Cadastro',
                          'updated': 'Atualização',
                          'archived': 'Arquivamento',
                          'primary_replaced': 'Principal substituído',
                        }[revision.kind] ??
                        'Atualização',
                  ),
                ),
            ],
          ],
        );
      },
    ),
  );
}
