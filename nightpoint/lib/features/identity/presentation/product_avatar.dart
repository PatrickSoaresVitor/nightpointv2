import 'package:flutter/material.dart';

/// Local representation only: no profile data is sent to an image provider.
class ProductAvatar extends StatelessWidget {
  const ProductAvatar({
    super.key,
    required this.nickname,
    this.style,
    this.radius = 36,
  });
  final String nickname;
  final String? style;
  final double radius;
  static const styles = {
    'np-initials': 'Iniciais',
    'np-car': 'Carro',
    'np-helmet': 'Capacete',
  };

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final icon = switch (style) {
      'np-car' => Icons.directions_car_outlined,
      'np-helmet' => Icons.sports_motorsports_outlined,
      _ => null,
    };
    return Semantics(
      label: 'Representação do seu perfil',
      child: CircleAvatar(
        radius: radius,
        backgroundColor: colors.secondaryContainer,
        foregroundColor: colors.onSecondaryContainer,
        child: icon != null
            ? Icon(icon, size: radius)
            : Text(
                nickname.isEmpty
                    ? '?'
                    : String.fromCharCode(nickname.runes.first),
                style: TextStyle(fontSize: radius * .8),
              ),
      ),
    );
  }
}
